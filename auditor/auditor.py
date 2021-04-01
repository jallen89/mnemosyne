#!/usr/bin/python3
"""
ChromeHandler -- The top-level handler which handles communication between
the browser and the auditor.
"""

from collections import defaultdict
import sys
from urllib.parse import urlparse
import signal
import websocket
import logging
import os.path
from datetime import datetime

from modules import dev_tools
from modules import utils
from modules import common
from modules import graph as g
from modules import frame_handler
from modules import base

class ChromeHandler(base.Handler):
    """ChromeHandler attaches to the browser target."""

    def handle_new_browsing_session(self):
        session_id = utils.random_string_digits(32)
        session = g.Session(session_id, self.user_agent)
        session.log(self.logger)
        print("Current session: " + session_id)
        user = g.User(self.user_id)
        user.log(self.logger)
        user_edge = g.SessionEdge(self.user_id, g.Session.Instance().get_session_id())
        user_edge.log(self.logger)

    def __init__(self, debug=False):
        """The top-level handler which listens for message across devtools."""
        self.messages = list()
        self.targets_attached = set()
        self.request_map = dict()

        self.user_id = utils.get_user_id()
        self.called = 0

        # Attach to the browser id
        self.handler_id = "ChromeHandler"
        base.Handler.__init__(self, self.handler_id, debug)
        
        self._init_connections()
        
        # Initializes logger
        self.file_cache = utils.FileCache(common.SCRIPT_CACHE)
        self.logger = utils.ObjectManager("neo4j-csvs")
        # Maintains a list of messages that need to be parsed.
        self.frame_handler = frame_handler.FrameHandler(self)
        self.handle_new_browsing_session()

    def _init_connections(self):
        self.chrome = dev_tools.ChromeInterface()
        version_output = self.chrome.attach_to_browser_target()
        self.user_agent = version_output['User-Agent']
        session_id_m, msgs = self.chrome.Target.attachToBrowserTarget()
        self.browser_session_id = session_id_m['result']['sessionId']
        self.target_id = msgs[0]['params']['targetInfo']['targetId']
        targets, msgs = self.chrome.Target.getTargets()
        self.messages.extend(msgs)
        targets = targets['result']['targetInfos']
        for target in targets:
            self.attach_to_target(target)

    def attach_to_target(self, info, m=None):
        """Enables the DevTool's domains that we need messages from."""
        # Register for messages
        def enable(func, **kwargs):
            kwargs['sessionId'] = session_id
            result, msgs = func(**kwargs)
            if 'Timeout' in result:
                self.log.error("NoReturn: {}:{}:{}:{}".format(
                    func, dict(kwargs), target_id, m))
            self.messages.extend(msgs)
            return result

        target_id = info['targetId']
        if target_id in self.targets_attached:
            self.log.warning("Have already attached {}".format(info))
        else:
            self.targets_attached.add(target_id)

        # Attach to the target.
        session_id_m, msgs = self.chrome.Target.attachToTarget(
            targetId=target_id, flatten=True)
        self.messages.extend(msgs)

        if 'error' in session_id_m:
            self.log.error("Error Attaching {}-{}".format(info, session_id_m))
            return

        self.messages.extend(msgs)
        session_id = utils.get_session_id(session_id_m)


        print("called", self.called)
        self.called +=1

        # Enable the inspectors we need.
        enable(self.chrome.Target.setDiscoverTargets, discover=True)
        # we will handle windowOpen in targetCreated, set windowOpen=False
        enable(self.chrome.Target.setAutoAttach, autoAttach=False,
               flatten=True, waitForDebuggerOnStart=False, windowOpen=False)
        enable(self.chrome.Page.enable)
        enable(self.chrome.Network.enable)
        enable(self.chrome.Debugger.enable)
        enable(self.chrome.Page.setLifecycleEventsEnabled, enabled=True)

    def msg_loop(self):
        """The message loop is the main loop for parsing received messages.

        1. Check if any new messages exists.
        2. If we have a message, then we check if this is a message we want
           to parse.
        3. If so, get the corresponding parsing method using self.handlers
        4. Finally, if the handler returns True it implies we need to shutdown.

        * If a KeyboardInterrupt is received, then we will begin shutting down.
        """
        #self.log.debug("Chrome msg_loop is initiated.")
        while True:
            try:
                #TODO: If an exception occurs, we should not stop the auditor
                # untill all messages have been parsed.
                m = self.chrome.pop_messages()
                self.messages.extend(m)
                while len(self.messages):
                    m = self.messages.pop(0)
                    shutdown = self.run_cycle(m)
                    if shutdown:
                        self.shutdown("shutdown")
                        break
            except KeyboardInterrupt:
                self.log.info("KeyboardInterrupt, shutting down.")
                self.shutdown("shutdown")
                break
            except websocket._exceptions.WebSocketConnectionClosedException:
                self.log.info("Websocket exception, shutting down.")
                self.shutdown("shutdown")
                break

    def handle_dom_document_updated(self, m):
        """Handle DOM.documentUpdated messages.

        NOTE: We only receive DOM events for the DOM events we "know", so we
        request all DOM nodes once the document have been completely updated.
        This will allow us to track any DOM modifications for all nodes.
        """
        return
        nodes, msgs = self.chrome.DOM.getFlattenedDocument(depth=-1,
                                                           pierce=True)
        self.messages.extend(msgs)

    def handle_frame_attached(self, m):
        self.frame_handler.handle_frame_attached(m)

    def handle_frame_navigated(self, m):
        self.frame_handler.handle_frame_navigated(m)

    def handle_response_received(self, m):
        p = m['params']
        r = p['response']

        self.frame_handler.handle_response_received(m)
        request_id = p['requestId']
        #XXX: Is the request map still necessary?
        if request_id in self.request_map:
            request = self.request_map[request_id]
            edge = g.ResponseEdge.from_m(m, request)
            edge.log(self.logger)

    def handle_request_sent(self, m):
        p = m['params']
        loader_id = p['loaderId']
        frame_id = p.get('frameId')

        if not frame_id:
            return

        edge = g.RequestEdge.from_m(m)
        self.frame_handler.handle_request_sent(m)
        self.request_map[p['requestId']] = edge
        edge.log(self.logger)

    def handle_download_begin(self, m):
        edge = g.DownloadEdge.from_m(m)
        edge.log(self.logger)

    def handle_script_parsed(self, m):
        self.frame_handler.handle_script_parsed(m)
        return
        #TODO: How do we want to handle the script cache going forward?
        p = m['params']
        script_id = p['scriptId']
        url = p['url']
        s_hash = p['hash']
        frame_id = p['executionContextAuxData']['frameId']
        frame = self.frame_handler.get_frame(frame_id)
        # We need to create a script node, and a script2frame node.
        script = g.Script.from_m(m, frame_id, frame.loader_id)
        self.logger.add(g.SCRIPT, script)
        return
        try:
            msg, new_messages = self.chrome.Debugger.getScriptSource(
                scriptId=script_id)
            self.messages.extend(new_messages)
            if msg:
                src = msg['result']['scriptSource']
                self.file_cache.cache_file(src, s_hash)
        except websocket._exceptions.WebSocketConnectionClosedException:
            #XXX. The target has been deatched, but we are still parsing
            # incoming messages from it. However, we can't request anything
            # from browser, since this target no longer exists.
            return

    def handle_window_open(self, m):
        #TODO 11/13/2019 need to confirm whether this is duplicated with target_created 
        pass

    def handle_js_dialog_opening(self, m):
        #TODO
        pass

    # def handle_page_started_loading(self, m):
    #     # print("Started loading at ", datetime.now().timestamp())
    #     timestamp = datetime.now().timestamp()
    #     # print("Start: ", timestamp)
    #     utils.new_load(m['params']['frameId'], timestamp)

    # def handle_page_stopped_loading(self, m):
    #     timestamp = datetime.now().timestamp()
    #     # print("Stop: ", timestamp)
    #     (start, stop) = utils.stop_load(m['params']['frameId'], timestamp)
    #     print("\033[92m {}\033[00m" .format("[+] Frame " + m['params']['frameId'] + " loaded in " + str(stop - start) + "s"))

    def handle_target_created(self, m):
        if (m.get('params') and not m['params']['targetInfo']['attached']
                and m['params']['targetInfo']['type'] == 'page'):
            self.attach_to_target(m['params']['targetInfo'])
        self.frame_handler.handle_target_created(m)

    def handle_target_attached(self, m):
        p = m['params']
        info = p['targetInfo']
        if p['waitingForDebugger']:
            session_id = m['sessionId']
            try:
                self.log.debug("Attaching to {}".format(m))
                result, msgs = self.chrome.Runtime.runIfWaitingForDebugger(
                    sessionId=session_id)
                self.messages.extend(msgs)
            except websocket._exceptions.WebSocketTimeoutException:
                self.log.error("Could not start target {}".format(m))
                return

        self.frame_handler.handle_attached_to_target(m)

    def handle_target_info_changed(self, m):
        p = m['params']
        info = p['targetInfo']
        target_types = ['page', 'iframe']

    def shutdown(self, m):
        """Exit routine, closes DevTools socket & flushes all logs to disk."""
        # Call base.Handler's shutdown routine.
        base.Handler.shutdown(self, m)
        self.frame_handler.handle_shutdown()
        self.chrome.close()
        self.logger.flush_all(exiting=True)
        self.log.info("{}'s handler is shutdown (flushing complete).".format(
            self.handler_id))

    handlers = {
        "Network.responseReceived": handle_response_received,
        "Network.requestWillBeSent": handle_request_sent,
        "Page.frameAttached" : handle_frame_attached,
        "Page.frameNavigated" : handle_frame_navigated,
        "Page.downloadWillBegin" : handle_download_begin,
        "Debugger.scriptParsed" : handle_script_parsed,
        "Page.windowOpen" : handle_window_open,
        "Page.javascriptDialogOpening": handle_js_dialog_opening,
        "Target.targetCreated" : handle_target_created,
        "Target.attachedToTarget" : handle_target_attached,
        "Target.targetInfoChanged" : handle_target_info_changed,
    }

if __name__ == '__main__':
    manager = ChromeHandler().msg_loop()
