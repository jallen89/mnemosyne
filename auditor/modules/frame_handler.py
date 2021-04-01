"""
FrameHandler -- Maintains the state of frames during the auditing.
"""
import copy
from collections import defaultdict
from modules import common
from modules import graph as g
from modules import utils
from modules import base
import json, pprint

class FrameHandlerError(Exception):
    def __init__(self, msg):
        print(msg)

class FrameHandler(base.ObjectHandler):
    """Manages frame-caching for a handler."""

    instance = None

    def __init__(self, handler, debug=True):
        """Initializes a FrameCache for a Handler class.."""

        if self.instance:
            raise FrameHandleError("A Frame handler already exists.")

        id_ = 'frame-handler-{}'.format(handler.handler_id)
        super().__init__(id_, handler, debug)
        self.entries = dict()
        FrameHandler.instance = self

        #NOTE: We flush the framehandler every 1000 frames.
        self.flush_threshold = 100


    @classmethod
    def Instance(cls):
        """ Returns an instance to the Frame handler."""

        if not FrameHandler.instance:
            raise FrameHandlerError("Frame handler has not been created.!")
        else:
            return FrameHandler.instance

    @classmethod
    def GetFrame(cls, frame_id):
        """Call to get frame for a specific frame id."""
        return cls.Instance().get_frame(frame_id)


    def handle_target_created(self, m):
        p = m['params']
        info = p['targetInfo']

        if not(info['type'] == 'iframe' or info['type'] == 'page'):
            return

        frame_id = info['targetId']
        frame = self.emplace(frame_id)
        # Get a reference to the frame's opener.                                
        if info['type'] == 'page' and info['url'] and 'openerId' in info:
            assert(info['openerId'] in self.entries), m
            opener = self.get_frame(info['openerId'])
            self.log.debug("Opener Frame {}".format(opener))
            frame.opener = opener
        frame.observed_creation = True

        if info['url']:
            frame.properties['url'] = info['url']

        if info['title']:
            frame.properties['title'] = info['title']

        frame.properties['type'] = info['type']

    def handle_attached_to_target(self, m):
        p = m['params']
        info = p['targetInfo']

        # Currently we don't bootstrap iframes. We may need to do this
        # in the future. However, there hasn't been any issues at this
        # point.
        if info['type'] != 'page':
            return
        frame_id = p['targetInfo']['targetId']
        frame = self.get_frame(frame_id)
        if frame and frame.observed_creation:
            return

        #XXX: This is a very special case that only occurs when the frame 
        # was created prior to the auditing. In this case, a lot of state 
        # information that we need to maintain about the frame will
        # not be provided. In this case, we bootstrap the state of the frame
        # by quering the frame tree, which will provide us with the loaderID.
        # After that we also set the has_navigated and has_attached flags.
        result, msgs = self.chrome.Page.getFrameTree(sessionId=p['sessionId'])
        self.handler.messages.extend(msgs)
        #XXX: We many need to recursively call this. 
        root = result['result']['frameTree']['frame']
        frame = g.Frame.from_m({'params' : {'frame' : root}})
        frame.has_navigated = True
        frame.has_attached = True

        self.entries[frame.frame_id] = frame

    def handle_frame_attached(self, m):
        p = m['params']
        parent = self.get_frame(p['parentFrameId'])
        assert(parent), "Parent doesn't exist: {}".format(m)
        child = self.emplace(p['frameId'])
        assert(not child.parent
               or child.parent.frame_id == p['parentFrameId']), \
               "Child already has parent{} {} {}".format(child, parent, m)
        child.creator = utils.get_caller_from_stack(m)
        child.parent = parent
        child.has_attached = True

    def handle_frame_navigated(self, m):
        p = m['params']
        f = p['frame']
        current = self.get_frame(f['id'])
        frame = g.Frame.from_m(m)

        self.log.debug("Frame Navigated: {}".format(m))

        if not current:
            # This is an extremely rare corner case, which only happens once
            # every ~10 minutes on sites such as CNN, Forbes, etc. Essentially, 
            # an iframe navigates before it is attached. I am not sure why this
            # occurs, but I am assuming it also a race that we lose (similar to
            # high-priority network requests). Therefore, we just treat it as a
            # special case. Since it is just for iframes, it is not a major
            # issue. 
            assert(frame.properties['url'] ==  'about:blank')
            frame.has_navigated = True
            self.entries[frame.frame_id] = frame
        elif current == frame:
            # We don't need to log here.
            assert(current.loader_id == frame.loader_id)
            #XXX: When multiple windows are used, this assumption is no longer
            # holding?
            #assert(current.network_set_loader), current
            current.has_navigated = True
        elif current.loader_id == 0:
            current.has_attached = frame.has_attached
            #XXX: Is this update safe?
            current.properties.update(frame.properties)
            current.loader_id = frame.loader_id
            current.has_navigated = True
        else:
            # The current frame must be logged at this point.
            assert(current.loader_id), current
            self.log.debug("cur: {}: {}".format(current.loader_id, current))
            self.log.debug("frame: {}: {}".format(frame.loader_id, frame))
            current.log(self)
            frame.has_attached = current.has_attached
            frame.prev_version = current
            frame.navigated_from = current
            frame.has_navigated = True
            self.entries[frame.frame_id] = frame

    def _handle_redirect_request(self, m, frame):
        # If the frame's loader_id is 0, this indicates that an iframe
        # probably made the request, and *shouldn't* redirect
        # This still needs to be confirmed.
        p = m['params']
        i = p['initiator']
        if (p['requestId'] == p['loaderId'] and i['type'] == 'script'
            and frame and frame.loader_id != 0):

            record = g.RedirectRecord.create(m, frame)
            self.log.debug("Created Redirect record {}".format(record))
            record.log(self)

            # pp = pprint.PrettyPrinter(indent=4)
            # pp.pprint(json.dumps(m))
            # print("\n")


    def handle_request_sent(self, m):
        p = m['params']
        initiator = p['initiator']
        request = p['request']
        frame = self.get_frame(p['frameId'])
        self._handle_redirect_request(m, frame)
        #XXX: https://cs.chromium.org/chromium/src/third_party/blink/renderer/core/inspector/inspector_page_agent.cc
        # If the frame isn't in the cache at this point, then it means we
        # haven't received the frameAttached message. In the
        # inspector_agent_page.cc code it shows that the page inspector will try
        # to flush FrameAttached messages before network events referencing the
        # frame are reported. However, it seems that when the priority is
        # 'VeryHigh' or 'High' the page inspector will not always win the race. 
        #XXX: This can also occur when windowOpen occurs, since the current 
        # impl of attach the debugger on window open doesn't work.
        if not frame:
            frame = self.emplace(p['frameId'])
            frame.loader_id = p['loaderId']
            # We need to let other handlers know we inserted the loader.
            frame.properties['requests'] += 1
            frame.network_set_loader = True
            if 'url' not in frame.properties or not frame.properties['url']:
                frame.properties['url'] = p['documentURL']
            frame.network_inserted = True

        if p['initiator'] == 'parser':
            frame.properties['requests'] += 1
            assert(frame.has_navigated and frame.loader_id == p['loaderId'])
            return

        if not frame.has_navigated:
            assert(frame.loader_id == 0 or frame.network_set_loader), \
                    "{}-{}-{}".format(frame, m, frame.loader_id)
            #XXX: We will preemptively update the loader ID. 
            # IF the frame navigates, it MUST verify this loaderID matches.
            frame.properties['requests'] += 1
            frame.loader_id = p['loaderId']
            frame.network_set_loader = True
            if 'url' not in frame.properties or not frame.properties['url']:
                frame.properties['url'] = p['documentURL']

    def handle_response_received(self, m):
        p = m['params']
        return
        loader_id = p['loaderId']
        frame_id = p['frameId']
        frame = self.get_frame(frame_id)
        assert(frame), m
        frame = g.Frame(frame_id, loader_id)
        current.properties['responses'] += 1

    def handle_script_parsed(self, m):
        p = m['params']
        try:
            frame_id = p['executionContextAuxData']['frameId']
        except:
            return
            raise FrameHandlerError("Frame ID doesn't exist {}".format(m))

        frame = self.emplace(frame_id)
        frame.properties['exec_context'] = str(int(p['executionContextId']))
        frame.properties['scripts_parsed'] += 1
        frame.exec_context = str(int(p['executionContextId']))
        frame.scripts.add(p['scriptId'])
        # Add message to the frame's script message queue.
        frame.script_messages.append(m)

    def emplace(self, frame_id, loader_id=0):
        """Get a frame and insert it if it's new."""
        frame = self.get_frame(frame_id)
        if not frame:
            frame = self.add_new_frame(frame_id, loader_id)
        return frame

    def get_frame(self, frame_id):
        """ Get frame if in frame cache."""
        frame = self.entries[frame_id] if frame_id in self.entries else None
        return frame

    def add_new_frame(self, frame_id, loader_id=0):
        """Add a new frame it it doesn't exist."""
        assert(frame_id not in self.entries)
        frame = g.Frame(frame_id, loader_id)
        self.entries[frame_id] = frame
        return frame

    def handle_shutdown(self):
        for entry in self.entries.values():
            if not entry.is_logged:
                entry.log(self)
        self.flush_all(exiting=True)
