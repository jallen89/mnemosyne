import uuid
import hashlib
import base64
from urllib.parse import urlparse
from modules import utils
from modules import frame_handler
from modules import script_handler


NET_EDGE = "network-edges"
FRAME_EDGE = "frame-edges"
RES_EDGE = "resource-edges"
REQ_EDGE = "request-edges"
REQUEST_EDGE = REQ_EDGE
RESPONSE_EDGE = "response-edges"
LOAD_EDGE = "loader-edges"
HOST = "hosts"
HOST = "hosts"
RESOURCE = "resources"
DOWNLOAD = "download"
NAV_EDGE = "navigation-edges"
NAVIGATED = NAV_EDGE
CREATED = "created"
SEND_EDGE = "network-send-edges"
FRAME = "frames"
SCRIPT = "scripts"
PARSER = "parser"
OPENED = "opened"
PARENT = "parent"
FRAME_ATTACHED = "frame-attached"
REDIRECT = "redirect"
USER = "user"
SESSION = "session"
STARTED = "started"


def add_properties(str_in, properties):
    if properties:
        str_out = str_in + DELIM + DELIM.join(list(properties.values()))
    else:
        str_out = str_in
    return str_out


class GraphError(Exception):
    pass


class ElementError(Exception):
    pass



class Edge(object):
    def __init__(self, start, end, label=None, id=None, type=None, debug=True):
        self.start = start
        self.debug = debug
        self.end = end
        self.label = label
        self.type = type
        self.id = "{}-{}:{}->{}".format(label, id, start, end)
        self.properties = dict()
        self.p = self.properties
        self.properties['start'] = self.start
        self.properties['end'] = self.end
        self.properties['global_session_id'] = Session.Instance().get_session_id()

        if self.debug:
            self.properties['who_created'] = utils.which_handler()

    def to_row(self):
        return zip(*[("start", self.start), ("end", self.end)]
                   + list(self.properties.items()))
    def __str__(self):
        return "{}->{}: {}".format(self.start, self.end, self.properties)

    def __eq__(self, other):
        return (self.start == other.start and self.end == other.end)

    def __hash__(self):
        return hash(self.start  + self.end)

    def __getattr__(self, attr):
        if attr in self.__dict__:
            return self.__dict__[attr]
        elif attr in self.properties:
            return self.properties[attr]
        else:
            raise AttributeError

    def log(self, log_handle):
        if self.debug:
            self.properties['who_logged'] = utils.which_handler()
        log_handle.add(self.label, self)

E = Edge

class DownloadEdge(Edge):

    def __init__(self, path, frame):
        super().__init__(frame.id, path, DOWNLOAD)

    @classmethod
    def from_m(cls, m):
        p = m['params']
        frame_id = p['frameId']
        url = urlparse(p['url'])
        domain = url.netloc
        #XXX. This is the path on the remote server.
        path = url.path

        frame = frame_handler.FrameHandler.GetFrame(frame_id)
        edge = DownloadEdge(path, frame)
        edge.properties['domain'] = domain
        edge.properties['path'] = url.path
        return edge

class ResponseEdge(Edge):
    """(host)<-[:LOCATION]-(resource)<-[:RESPONSE]-(script)"""

    def __init__(self, request):
        super().__init__(request.end, request.start, "Response",
                         request.requestId)
        self.host = None

    @classmethod
    def from_m(self, m, request):
        p = m['params']
        r = p['response']
        h = r['headers']

        edge = ResponseEdge(request)
        edge.p['status'] = str(r['status'])
        edge.host = Host.from_response_m(m)
        if edge.host:
            edge.p['rip'] = edge.host.rip
        return edge

    def log(self, log_handle):
        if self.host:
            log_handle.add(HOST, self.host)
        log_handle.add(RESPONSE_EDGE, self)


class RequestEdge(Edge):
    """(frame)-[:COMPILE]->(script)-[:request]->(resource)"""

    def __init__(self, script_id, resource, request_id, debug=True):
        super().__init__(script_id, resource, "Request", request_id)
        if self.debug:
            self.properties['who_created'] = utils.which_handler()

    @classmethod
    def from_m(self, m):
        p = m['params']
        r = p['request']
        h = r['headers']
        i = p['initiator']

        # Get or Create Script ID.
        if i['type'] == 'script':
            caller = utils.get_caller_from_stack({'params' : i })
            if caller:
                script = Script(caller['scriptId'], p['frameId'], p['loaderId'])
                script.properties['url'] = i['stack']['callFrames'][0]['url']
            else:
                raise ElementError("No callstack found! {}".format(m))
        elif i['type'] == 'parser':
            #frame = frame_handler.FrameHandler.GetFrame(p['frameId'])
            script = Parser(p['frameId'], p['loaderId'])
            script.properties['scriptId'] = script.id
        else:
            script = Script(i['type'], p['frameId'], p['loaderId'])
            script.url = "None"

        # Resource
        resource = Resource.from_request_m(m)
        edge = RequestEdge(script.id, resource.id, p['requestId'])
        edge.p['requestId'] = p['requestId']
        edge.p['method'] = r['method']
        edge.p['timestamp'] = str(p['timestamp'])
        edge.p['wallTime'] = str(p['wallTime'])
        edge.p['hasUserGesture'] = str(p['hasUserGesture'])
        edge.p['type'] = p['type']
        edge.script = script
        edge.resource = resource

        return edge

    def log(self, log_handle):
        log_handle.add(REQUEST_EDGE, self)
        #XXX? Why do we need to log the script here instead of when it was
        # parsed? We are assuming we will always have been a debug.scriptParsed
        # message before this, is this assumption true?
        #Q: Are there any other issues if the script isn't logged here?
        if type(self.script) == Parser:
            log_handle.add(PARSER, self.script)

        log_handle.add(RESOURCE, self.resource)


class OpenedEdge(Edge):
    """(parent-frame)-[:OPENED]->(child-frame)"""

    def __init__(self, parent, child):
        super().__init__(parent.id, child.id, OPENED)


class ParentChildEdge(Edge):
    """ (parent)-[:PARENT]->(child) """

    def __init__(self, parent, child):
        super().__init__(parent.id, child.id, PARENT)


class FrameAttached(Edge):

    def __init__(self, frame, parent):
        super().__init__(parent.id, frame.id, FRAME_ATTACHED)

    @classmethod
    def from_m(self, m, frame, parent):
        p = m['params']
        edge = FrameAttached(frame, parent)
        #NOTE(joey): Should we get the entire callstack? Additionally, this can
        # identify nested scripts.
        #TODO: We need to collect the entire traceback, or at least try to
        # identify the relevant script, o.w. we are most likely to see jquery.
        if 'stack' in p:
            callframe = p['stack']['callFrames'][0]
            edge.properties['scriptId'] = callframe['scriptId']
            edge.properties['url'] = callframe['url']

        return edge


class FrameNavigated(Edge):
    def __init__(self, prev_version, frame):
        super().__init__(prev_version.id, frame.id, NAVIGATED)
        if frame.transition_type:
            self.properties['transitionType'] = frame.transition_type

class CreatedFrame(Edge):
    def __init__(self, frame, creator_id):
        super().__init__(frame.id, creator_id, CREATED)

class SessionEdge(Edge):
    def __init__(self, user_id, session_id):
        super().__init__(user_id, session_id, STARTED)


class Record(object):

    def __init__(self, record_id, label, debug=True):
        self.id = record_id
        self.label = label
        self.debug = debug
        self.properties = dict()
        self.properties['id'] = self.id
        self.properties['global_session_id'] = Session.Instance().get_session_id()

        if self.debug:
            self.properties['who_created'] = utils.which_handler()

    def __eq__(self, other):
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __str__(self):
        return "{}: {}".format(self.id, self.properties)

    def to_row(self):
        return zip(*[("id", self.id)] + list(self.properties.items()))

    def log(self, log_handle):
        if self.debug:
            self.properties['who_logged'] = utils.which_handler()
        log_handle.add(self.label, self)


class RedirectRecord(Record):

    def __init__(self, record_id, debug=True):
        super().__init__(record_id, REDIRECT)

    @classmethod
    def create(cls, m, old_frame):
        p = m['params']
        initiator = p['initiator']

        record_id = "{}-{}".format(old_frame.loader_id, p['requestId'])
        record = RedirectRecord(record_id)
        script_id = utils.get_script_id_from_stack(m)
        record.properties['scriptId'] = script_id
        record.properties['oldLoaderId'] = old_frame.loader_id
        record.properties['newLoaderId'] = p['loaderId']
        record.properties['frameId'] = p['frameId']
        return record

class Node(object):
    def __init__(self, node_id=None, debug=True):
        self.label = "Node"
        self.debug = debug
        self.id = node_id
        self.properties = dict()
        self.p = self.properties
        self.properties['id'] = self.id
        self.properties['global_session_id'] = Session.Instance().get_session_id()

        if self.debug:
            self.properties['who_created'] = utils.which_handler()


    def __eq__(self, other):
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __str__(self):
        return "{}: {}".format(self.id, self.properties)

    def __getattr__(self, attr):
        if attr in self.__dict__:
            return self.__dict__[attr]
        elif attr in self.properties:
            return self.properties[attr]
        else:
            raise AttributeError

    def to_row(self):
        return zip(*[("id", self.id)] + list(self.properties.items()))

    def log(self, log_handle):
        if self.debug:
            self.properties['who_logged'] = utils.which_handler()
        log_handle.add(self.label, self)


class Script(Node):
    #XXX: Remove loader_id
    def __init__(self, script_id, frame_id, loader_id=None):
        super().__init__("{}-{}-{}".format(script_id, frame_id, loader_id))
        self.label = SCRIPT
        self.properties['frameId'] = frame_id
        self.properties['loaderId'] = loader_id
        self.properties['scriptId'] = script_id

    @classmethod
    def from_m(cls, m, frame_id, loader_id):
        p = m['params']
        script = Script(str(p['scriptId']), frame_id, loader_id)
        script.p['exec_context'] = str(p['executionContextId'])
        script.p['url'] = p['url'] if 'url' in p else "None"
        script.p['hash']= p['hash']
        return script

    @classmethod
    def get_id(cls, frame_uuid, script_id):
        return "{}-{}".format(frame_uuid, script_id)

    def __eq__(self, other):
        #XXX. Hacky way to try and get the URL. In some cases the Script object
        # that was created may not actually have this information, but a later
        # audit entry will. Since their ids are equal, the latter will not be
        # stored, which means we will lose the ID. 
        #XXX: Is this still needed?
        if self.id == other.id and self.p['url'] == 'None':
            self.p['url'] = other.p['url']

        return self.id == other.id


class Parser(Node):
    def __init__(self, frame_id, loader_id):
        super().__init__("parser-{}-{}".format(frame_id, loader_id))
        self.label = PARSER
        self.properties['frameId'] = frame_id
        self.properties['loaderId'] = loader_id

class VersionEdge(Edge):
    def __init__(self, prev_version, frame):
        super().__init__(prev_version.id, frame.id, "Version")

class Frame(Node):
    def __init__(self, frame_id, loader_id, debug=True):
        super().__init__("{}-{}".format(frame_id, loader_id))
        #The Frame class has became a lot more complex and 
        # is now doing a lot more than what we originall intended
        # it to do. 
        # TODO: Determine the fields that are still necessary.
        # TODO: Organize/Comment the fields
        # TODO: Clean up the Frame object.
        self.label = FRAME
        self.parent = None
        self.scripts = set()
        self.observed_creation = False
        self.prev_version = None
        self.who_created = utils.which_handler()
        self.has_navigated = False
        self.has_parsed = False
        self.has_attached = False
        self.network_set_loader = False
        self.navigated_from = None
        self.network_inserted = False
        self.transition_type = None
        self.destination_url = None
        self.exec_context = None
        self.opener = False
        self.creator = None
        self.is_logged = False
        self._loader_id = loader_id
        self.properties['frame_id'] = frame_id
        self.properties['loader_id'] = self._loader_id
        self.properties['requests'] = 0
        self.properties['responses'] = 0
        self.properties['scripts_parsed'] = 0
        # Message queues: In some cases, we don't know enough information
        # about the Frame yet to handle some messages. For example, in some
        # cases we may learn that a script was parsed by this frame prior to 
        # learning the loaderId. Due to this, we can properly attribute the
        # script to a specific Frame. To address this, we rely on stashing 
        # the messages and then parsing them at a later time.
        self.script_messages = list()


    @classmethod
    def from_m(cls, m):
        p = m['params']
        f = p['frame']
        frame = Frame(f['id'], f['loaderId'])
        frame.p['url'] = f['url']
        frame.p['securityOrigin'] = f['securityOrigin']
        frame.p['mimeType'] = f['mimeType']
        frame.p['name'] = f['name'] if 'name' in f else "None"
        return frame

    @property
    def loader_id(self):
        return self._loader_id

    @loader_id.setter
    def loader_id(self, value):
        # The loader id may change from time-to-time. So we need to update the
        # node's ID when this occurs.
        self._loader_id = value
        self.properties['loader_id'] = value
        # Update ID if loader id changes.
        self.id = "{}-{}".format(self.frame_id, self.loader_id)
        self.properties['id'] = self.id


    def log_script_msgs(self):
        """Handle all the script messages place in queue."""

        if not self.script_messages:
            return
        handler = script_handler.ScriptHandler(self.handler, self)
        for m in self.script_messages:
            handler.run_cycle(m)
        handler.shutdown()

    def log(self, log_handle):
        """We log the frame as is, and bump the version."""

        super().log(log_handle)
        # Log the script messages.
        self.log_script_msgs()
        if self.parent:
            FrameAttached(self, self.parent).log(log_handle)
        if self.navigated_from:
            nav_edge = FrameNavigated(self.navigated_from, self)
            nav_edge.properties['reason'] = self.transition_type
            nav_edge.properties['destination'] = self.destination_url
            nav_edge.log(log_handle)
        if self.prev_version:
            VersionEdge(self.prev_version, self).log(log_handle)
        if self.creator:
            #XXX: Add function information.
            script = Script(self.creator['scriptId'], self.parent.frame_id,
                            self.parent.loader_id)
            #XXX: Should we assert the script id is in the parent's scripts?
            CreatedFrame(self, script.id).log(log_handle)
        if self.opener:
            OpenedEdge(self.opener, self).log(log_handle)
        self.is_logged = True


class Host(Node):
    def __init__(self, remote_ip, domain=None):
        super().__init__(remote_ip)
        self.label = HOST
        self.p['rip'] = remote_ip
        self.p['domain'] = domain

    @classmethod
    def from_response_m(self, m):
        p = m['params']
        r = p['response']
        h = r['headers']
        if 'remoteIPAddress' in r and r['remoteIPAddress']:
            rip = r['remoteIPAddress']
            domain = urlparse(r['url']).netloc
            host = Host(rip, domain)
        else:
            host =  None

        if host:
            if 'Server' in h:
                host.p['server'] = h['Server']
            elif 'server' in h:
                host.p['server'] = h['server']
            else:
                host.p['server'] = "None"

        return host

class User(Node):
    def __init__(self, user_id):
        super().__init__(user_id)
        self.label = USER

class Session(Node):

    instance = None

    def __init__(self, session_id, user_agent):
        # Ensure only 1 session exists.
        if not Session.instance:
            Session.instance = self
        else:
            raise GraphError("Only one Session should be created.")
            self.id = session_id
        super().__init__(session_id)
        self.label = SESSION
        self.p['user-agent'] = user_agent.replace(';', ':')

    @classmethod
    def Instance(cls):
        """Returns a reference to Session, making it globally accessible."""

        if Session.instance:
            return Session.instance
        else:
            raise GraphError("Session has not been initialized.")

    def get_session_id(self):
        return self.id


class Resource(Node):
    # We can collect forensic evidences related to the actor's infastructure.
    def __init__(self, path, resource_type):
        hashed_path = hashlib.sha256(str.encode(path)).hexdigest()
        super().__init__(hashed_path)
        self.label = RESOURCE
        self.p['path'] = path
        self.p['type'] = resource_type

    @classmethod
    def from_request_m(self, m):
        p = m['params']
        r = p['request']
        url = urlparse(r['url'])
        resource = Resource(url.netloc + url.path, p['type'])
        resource.p['domain'] = url.netloc
        return resource
