def target_handler(signum, frame):
    """If signal is received, shutdown target."""
    for obj in gc.get_objects():
        if isinstance(obj, Target):
            target = obj
            target.shutdown()
            print("Error: Control should not have reached here.!")


class Target(object):
    """Responsible for managing a single target (tab)."""
    def __init__(self, target, manager=None, handler_type=ChromeHandler):
        # adds targetId, type, title, url, attached, browserContextId members
        #XXX: This is hacky ><.
        for k,v in target.items():
            self.__dict__[k] = v
        # Create log file for this target.
        log_file = common.LOG_FILE_TEMPLATE.format(self.targetId)
        # A reference to global chrome manager.
        # XXX. This is dangerous/Doesn't make sense.
        self.manager = manager
        self.handler_type = handler_type
        # The manager will eventually start this process.
        self.p = Process(target=self.run, args=(), daemon=False)
        # State flags
        self.is_handler_running = False
        self.is_shutdown = False
        self.log = logging.getLogger("Target-{}".format(self.targetId))

    def run(self):
        # Set signal handler
        signal.signal(signal.SIGTERM, target_handler)
        self.chrome = dev_tools.ChromeInterface(auto_connect=False)
        self.chrome.connect_targetID(self.targetId)
        # Attach the handler to the target.
        self.handler = self.handler_type(self)
        self.is_handler_running = True
        try:
            self.log.info("Starting handler's message loop.")
            self.handler.msg_loop()
        except KeyboardInterrupt:
            self.log.warning("Received interrupt, beginning shutdown.")
            self.shutdown()
        except websocket._exceptions.WebSocketConnectionClosedException:
            self.log.warning("Websocket Error, shutting down!")
            self.shutdown()

    def shutdown(self):
        """Shutdown the target."""

        if self.is_shutdown:
            self.log.error("Attempting to reshutdown target!")

        if self.is_handler_running:
            self.handler.shutdown("shutdown")
            self.is_handler_runing = False

        self.is_shutdown = True
        self.log.info("Target is shutdown")
        sys.exit()

    def __str__(self):
        base = g.DELIM.join([self.targetId, self.type, self.title, self.url])
        if hasattr(self, "browserContextId"):
            base += g.DELIM + self.browserContextId
        return base

    def __eq__(self, other):
        return self.targetId == other.targetId

    def __hash__(self):
        return hash(self.targetId)

class ChromeManager(object):
    """ The ChromeManager is responsible for listening for Devtool messages
    related to target creation. When a new tab-target is created, it will also
    create a new Target object and start the target's process.

    w.r.t to the audit logs, the ChromeManager will only collect the necessary
    information to reconstruct the parent-child relationships between parents.
    """

    def __init__(self):
        # A list of handler objects, each responsible for its own tab.
        self.log = logging.getLogger("Manager")
        self.targets = list()
        self.main_handler = dev_tools.ChromeInterface()
        self.main_handler.attach_to_browser_target()
        sesson_id_m, msgs = self.main_handler.Target.attachToBrowserTarget()
        #self.browser_session_id = session_id
        sys.exit()

        #NOTE: These two objects should be in the Target class.
        self.file_cache = utils.FileCache(common.SCRIPT_CACHE)
        self.logger = utils.ObjectManager(common.CSV_DIR)
        # Listen for target creation events.
        #self.main_handler.Target.setDiscoverTargets(discover=True)
        #TODO: The ObjectManager should be responsible for directory creation.
        try:
            os.mkdir(common.LOG_DIR)
        except FileExistsError:
            pass
        # Boot strap the initial targets. These are tabs that were already
        # created before the auditor started running.
        #targets = self.main_handler.Target.getTargets()[1][0]['result']
        #for target in targets['targetInfos']:
        #    self._create_target(target)
        self.main_msg_loop()

    def main_msg_loop(self):
        """ The main msg loop, which is responsible for listening for new
        target creation."""
        #FIXME: The man_msg_loop needs a message list similar Target.
        while True:
            try:
                for m in self.main_handler.pop_messages():
                    if 'method' not in m:
                        self.log.warning("No method {}".format(m))
                    elif m['method'] in self.handlers:
                        # print(m)
                        m_str = self.handlers[m['method']](self, m)
            except KeyboardInterrupt:
                self.shutdown(m)

    def shutdown(self, m):
        #FIXME: Ideally, the manager should also signal any children to enter 
        # their shutdown routines.
        self.main_handler.close()
        self.logger.flush_all(exiting=True)
        sys.exit()

    def handle_target_created(self, m):
        pass
        t_info = m['params']['targetInfo']
        #print(m)
        if t_info['type'] == 'page':
            self._create_target(t_info)

    def _create_target(self, info):
        if (info['type'] == 'page' and info['url'] == 'chrome://newtab/'):
            t = Target(info, self)
            #self.log_target_info(t)
            t.p.start()
            self.targets.append(t)

    def log_target_info(self, target):
        """Log information to track how each tab was opened."""
        self.logger.add("targets", target)
        opener = target.openerId if hasattr(target, "openerId") else "NewTab"
        self.logger.add("target-edges", g.Edge(opener, target.targetId, "lbl"))

    handlers = {
        "Target.targetCreated" : handle_target_created,
        "Inspector.detached" : shutdown
    }

