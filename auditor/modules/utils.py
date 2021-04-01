import os
import traceback
import glob
import random
import string
from weakref import WeakSet
from collections import defaultdict
from datetime import datetime

#from modules import graph as g
from modules.common import *

import pandas as pd

#TODO(Andrew): Update session-id code to access the session id using
# g.Session.Instance().get_session_id() method instead of using global
# variable.
global_session_id = ""
load_dict = {}

def get_session_id(m):
    return m['result']['sessionId']

def new_load(frame_id, time):
    load_dict[frame_id] = (time, 0)

def stop_load(frame_id, time):
    start_tuple = load_dict[frame_id]

    tuple_list = list(start_tuple)
    tuple_list[1] = time

    load_dict[frame_id] = tuple(tuple_list)
    return load_dict[frame_id]

def get_user_id():
    #print(container.name)
    user_id = os.environ.get('HOSTNAME')
    if not user_id:
        user_id = 'default-user-ID'
    return user_id

def get_caller_from_stack(m):
    """Returns the caller on the bottom of the call stack."""
    p = m['params']

    if 'stack' in p:
        stack = p['stack']
    elif 'initiator' in p and 'stack' in p['initiator']:
        stack = p['initiator']['stack']
    else:
        return None

    caller = stack['callFrames'][0]
    return caller

def get_script_id_from_stack(m):
    """Returns the scriptId on the bottom of the call stack."""
    caller = get_caller_from_stack(m)
    return caller['scriptId']


def which_handler():
    """Utility function to determine which handler called this function. Only
    useful for debugging."""

    ss = traceback.extract_stack()
    for frame in ss:
        if frame.name.startswith('handle_'):
            return frame.name

def random_string_digits(stringLength):
        """Generate a random string of letters and digits """
        lettersAndDigits = string.ascii_letters + string.digits
        return ''.join(random.choice(lettersAndDigits) for i in range(stringLength))

class FileCache(object):

    def __init__(self, dirname, is_bytes=False):
        self.dirname = dirname

        self.mode = "wb" if is_bytes else "w"

        try:
            os.mkdir(dirname)
        except FileExistsError:
            pass

    def cache_file(self, content, filename):
        """Create a new file in the File cache."""
        out_path = os.path.join(self.dirname, filename)

        if os.path.exists(out_path):
            return

        with open(out_path, self.mode) as outfile:
            outfile.write(content)


class FileLogger(object):

    def __init__(self, filename):
        self.file = open(filename, 'w+')

    def write(self, msg):
        self.file.write("{0}\n".format(msg))
        self.file.flush()

    def flush_iterable(self, iterable):
        for l in iterable:
            self.write(l)

    def close(self):
        self.file.close()

class CSVLogger(object):
    """ Maintains a set of objects, which eventually will be stored in a
        csv file named @filename.

        In order for this class to support logging objects to a CSV, the class
        of the objects needs to have a (unique) id field and a dictionary of
        properties. The keys in properties become the rows and the values will
        become the values in the csv.

        This class may seem like overkill, but it is useful when you are not
        sure what objects will be created in the future, and little effort is
        needed to setup logging for the new class.

        NOTE: Currently, we have no flushing mechanism, since we are relying
              on pandas to create the actual CSV files. We are using pandas,
              since it allows us to easily create a CSV without defining the
              columns or shape of the csv, which is unknown by this class.
        """

    def __init__(self, filename, debug=True):
        self.filename = filename
        self.entries = defaultdict(dict)
        self.flushed = False
        self.debug = debug
        self.log = logging.getLogger("CSVLogger-{}".format(self.filename))

    def add(self, obj):
        if self.debug:
            handler = which_handler()
            obj.properties['handler'] = handler
        self.entries[obj.id] = obj.properties

    def flush(self):
        #XXX. IF we reach here after we are flushed, it means something

        if self.flushed:
            self.log.warning("CSV file is already flushed!")
        else:
            df = pd.DataFrame.from_dict(self.entries, orient='index')
            # If no entries, then dont' actually create the logs.
            if len(df.index):
                df.to_csv(self.filename, index=False, sep=DELIM)
            self.flushed = True

    def close(self):
        return


# We need to create a dict for each object that logs its id and properties.
class ObjectLogger(FileLogger):

    def __init__(self, filename, cache_size=0, debug=True):
        super(ObjectLogger, self).__init__(filename)
        self.filename = filename
        self.objects = set()
        self.debug = debug
        self.cache_size = cache_size


    def flush(self):
        self.flush_iterable(self.objects)

    def add(self, obj):
        self.objects.add(obj)


        if len(self.objects) > self.cache_size:
            self.flush_iterable(self.objects)
            self.objects = set()


class ObjectManager(object):
    """Manages a set of CSVLogger's.

    NOTE: Originally, it managed a set of ObjectLogger.
    """

    def __init__(self, dirname="neo4j-csvs", flush_threshold=50000):
        """
        @flush_threshold -- Flush to files after @flush_threshold entries.
        """

        if not os.path.exists(dirname):
            os.mkdir(dirname)

        self.dirname = dirname
        self.flush_threshold = flush_threshold
        self.entries_cnt = 0
        self.loggers = dict()

    def register_loggers(self, resource_names):
        for r in resource_names:
            self.register_logger(r)

    def register_logger(self, resource_name):
        out_path = self._create_logfile(resource_name)
        self.loggers[resource_name] = CSVLogger(out_path)

    def add(self, key, value):
        """ Create a new object logger if it doesn't exist, then add
        value to associated ObjectLogger."""
        # Register key if this is first time we have seen it.
        if key not in self.loggers:
            self.register_logger(key)
        self.loggers[key].add(value)

        # Rotate logs if necessary.
        if self.entries_cnt > self.flush_threshold:
            self.entries_cnt = 0
            #NOTE: We want to force file to close, so exiting = True.
            self.flush_all(exiting=True)
            self.loggers = dict()
        else:
            self.entries_cnt += 1

    def flush_all(self, exiting=False):
        for logger in self.loggers.values():
            logger.flush()
            if exiting:
                logger.close()

    def _create_logfile(self, resource_name):
        exp = os.path.join(self.dirname, resource_name)
        file_cnt = [int(f.split('.')[-2]) for f in glob.glob(exp + "*")]
        max_val = max(file_cnt) + 1 if file_cnt else 0
        timestamp = datetime.timestamp(datetime.now())
        out_file = "{}.{}.csv".format(resource_name, timestamp)
        out_path = os.path.join(self.dirname, out_file)
        return out_path
