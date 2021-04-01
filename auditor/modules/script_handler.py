from modules import base
from modules import graph as g


class ScriptHandler(base.ObjectHandler):

    def __init__(self, handler=None, frame=None, debug=False):
        """Initializes a ScriptHandler, for a frame."""

        id_ = 'script-handler-{}'.format(frame.id)
        super().__init__(id_, handler, debug)
        self.entries = dict()
        self.frame = frame
        self.handler = handler

    def handle_script_parsed(self, m):
        #XXX: We assume the frame object that is responsible for managing the
        # ScriptHandler has already finalized the frame_id and loader_id.
        #assert(self.frame.loader_id), "No loader id {}.".format(self.frame)
        assert(self.frame.exec_context), "No exec context {}".format(self.frame)
        script = g.Script.from_m(m, self.frame.frame_id, self.frame.loader_id)
        script.log(self)


    handlers = {
        "Debugger.scriptParsed" : handle_script_parsed
    }
