#!/usr/bin/python3

import json
import time

import requests
import websocket
import sys


TIMEOUT = 2


class DevToolsError(Exception):

    def __init__(self, error_msg, msgs=None):
        """
        msgs -- The msgs that had been received prior to the error.
        """
        self.msgs = msgs


class GenericElement(object):
    def __init__(self, name, parent):
        self.name = name
        self.parent = parent

    def __getattr__(self, attr):
        func_name = '{}.{}'.format(self.name, attr)

        def generic_function(**args):

            messages = self.parent.pop_messages()
            self.parent.message_counter += 1
            message_id = int('{}{}'.format(id(self), self.parent.message_counter))
            message_id = self.parent.message_counter
            session_id = args.pop('sessionId', None)
            call_obj = {'id': message_id, 'method': func_name, 'params': args}
            if session_id:
                call_obj['sessionId'] = session_id
            json.dumps(call_obj)

            self.parent.ws.send(json.dumps(call_obj))
            result, err = self.parent.wait_result(message_id)
            err.extend(messages)
            return (result, err)

        return generic_function


class ChromeInterface(object):
    message_counter = 0

    def __init__(self, host='localhost', port=9222, tab=0, timeout=TIMEOUT, auto_connect=True):
        self.host = host
        self.port = port
        self.ws = None
        self.tabs = None
        self.timeout = timeout

    def get_tabs(self):
        response = requests.get('http://{}:{}/json'.format(self.host, self.port))
        self.tabs = json.loads(response.text)

    def attach_to_browser_target(self):
        connected = False
        timer = 0
        response = None
        while not connected:
            try:
                response = requests.get(
                    'http://{}:{}/json/version'.format(self.host,self.port))
                connected = True
            except requests.exceptions.ConnectionError:
                time.sleep(1)
                timer += 10
        if response:
            self.info = json.loads(response.text)
        else:
            raise Exception('ERROR: Connection Failed to dev tool')
        self.ws = websocket.create_connection(self.info['webSocketDebuggerUrl'])
        self.ws.settimeout(self.timeout)
        return json.loads(response.text)

    def connect(self, tab=0, update_tabs=True):
        if update_tabs or self.tabs is None:
            self.get_tabs()
        wsurl = self.tabs[tab]['webSocketDebuggerUrl']
        self.close()
        self.ws = websocket.create_connection(wsurl)
        self.ws.settimeout(self.timeout)

    def connect_targetID(self, targetID):
        wsurl = 'ws://{}:{}/devtools/page/{}'.format(self.host, self.port, targetID)
        self.close()
        self.ws = websocket.create_connection(wsurl)
        self.ws.settimeout(self.timeout)

    def close(self):
        if self.ws:
            self.ws.close()

    # Blocking
    def wait_message(self, timeout=None):
        self.ws.settimeout(self.timeout)
        try:
            message = self.ws.recv()
        except:
            return None
        finally:
            self.ws.settimeout(self.timeout)

        return json.loads(message)

    # Blocking
    def wait_event(self, event, timeout=None):
        timeout = self.timeout
        start_time = time.time()
        messages = []
        matching_message = None
        while True:
            now = time.time()
            if now-start_time > timeout:
                break
            try:
                message = self.ws.recv()
                parsed_message = json.loads(message)
                messages.append(parsed_message)
                if 'method' in parsed_message and parsed_message['method'] == event:
                    matching_message = parsed_message
                    break
            except:
                print("no messsage received!")
                break
        return (matching_message, messages)

    # Blocking
    def wait_result(self, result_id, timeout=1):
        messages = []
        matching_result = None
        while True:

            try:
                message = self.ws.recv()
            except websocket._exceptions.WebSocketTimeoutException:
                print ("timeout")
                return ("Timeout", messages)


            parsed_message = json.loads(message)

            if 'result' in parsed_message and parsed_message['id'] == result_id:
                matching_result = parsed_message
                break
            elif 'error' in parsed_message:
                return (parsed_message, messages)
            else:
                messages.append(parsed_message)

        return (matching_result, messages)

    # Non Blocking
    def pop_messages(self):
        messages = []
        self.ws.settimeout(0)
        while True:
            try:
                message = self.ws.recv()
                parsed_message = json.loads(message)
                messages.append(parsed_message)
            except BlockingIOError:
                break
        self.ws.settimeout(self.timeout)
        return messages

    def __getattr__(self, attr):
        genericelement = GenericElement(attr, self)
        self.__setattr__(attr, genericelement)
        return genericelement
