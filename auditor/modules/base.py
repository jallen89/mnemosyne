import logging

from modules import utils
from modules import common

class Handler(object):
    def __init__(self, id, debug=False):
        self.id = id
        self.debug = debug
        self.subhandlers = list()
        debug = False

        log_handler = logging.FileHandler("/dev/null".format(self.id))
        log = logging.getLogger(self.id)
        log.setLevel(common.LOG_LEVEL)
        log.addHandler(log_handler)
        self.log = log
        self.log_handler = log_handler

        if debug:
            self.debug_logger = utils.FileLogger(
                "msgs/msgs-{}.log".format(self.id))

    def run_cycle(self, m):
        """Run msg loop cycle for message m."""
        shutdown = False

        if m and 'method' in m and m['method'] in self.handlers:
            if self.debug:
                self.debug_logger.write(m)

            shutdown = shutdown or self.handlers[m['method']](self, m)

        # Pass the message to any subhandlers that need it.
        for handler in self.subhandlers:
            handler.run_cycle(m)

        if shutdown:
            self.shutdown(m)

    def register_subhandler(self, handler):
        """Registers a subhandler, which this handler will propagate the msg to
           after it has handled the message."""
        self.subhandlers.append(handler)

    def shutdown(self, m):
        """Shutdown the handler and all subhandlers."""

        if self.debug:
            self.debug_logger.close()

        # Close all log handlers.
        if self.debug:
            self.log.removeHandler(self.log_handler)
            self.log_handler.flush()
            self.log_handler.close()

        for handler in self.subhandlers:
            handler.shutdown(m)

    handlers = dict()


class ObjectHandler(Handler, utils.ObjectManager):

    def __init__(self, id, handler=None, debug=True):
        utils.ObjectManager.__init__(self, dirname="neo4j-csvs")
        Handler.__init__(self, id, debug)

        self.handler = handler
        if handler and hasattr(handler, 'chrome'):
            self.chrome = handler.chrome

    def shutdown(self, m=None):
        Handler.shutdown(self, m)
        self.flush_all(exiting=True)
