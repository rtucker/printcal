#!/usr/bin/python
#
# Copyright (c) 2006-2007 Mark Eichin.
#
# (Distribution terms: MIT/X11 license.)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
#
import optparse
import os
## import syck # for now, consider something simpler
## syck's python extension is unmaintained and cheesy
import urllib
import getpass
# import ydump
import pycurl
import StringIO
import sys
import stat
import itertools
import operator
import string
import yaml
# get cElementTree from *somewhere*...
try:
    import cElementTree
except ImportError:
    try:
        import xml.etree.ElementTree as cElementTree
    except ImportError:
        import elementtree.ElementTree as cElementTree
import re
# Python version of BestPractical's Hiveminder todo.pl, so I can import it and extend it

# need to force some handlers for exposed objects...
yaml.constructor.Constructor.add_constructor(
    u'tag:yaml.org,2002:perl/hash:BTDT::Model::Task',
    yaml.constructor.Constructor.construct_yaml_map)

yaml.constructor.Constructor.add_constructor(
    u'tag:yaml.org,2002:perl/hash:BTDT::Model::User',
    yaml.constructor.Constructor.construct_yaml_map)

yaml.constructor.Constructor.add_constructor(
    u'tag:yaml.org,2002:perl/hash:BTDT::CurrentUser',
    yaml.constructor.Constructor.construct_yaml_map)



# Original docs:
"""This is a simple command-line interface to Hiveminder that loosely
emulates the interface of Lifehacker.com's todo.sh script."""

usage = """todo.py [options] list
  todo.py [options] add <summary>
  todo.py [options] edit <task-id> [summary]

  todo.py tag <task-id> tag1 tag2

  todo.py done <task-id>
  todo.py del|rm <task-id>

  todo.py [options] pending
  todo.py accept <task-id>
  todo.py decline <task-id>

  todo.py assign <task-id> <email>
  todo.py [options] requests

  todo.py hide <task-id> date

  todo.py comment <task-id>

  todo.py [options] download [file]
  todo.py upload <file>

    Options:
       --group                          Operate on tasks in a group
       --tag                            Operate on tasks with a given tag
       --pri                            Operate on tasks with a given priority
       --due                            Operate on tasks due on a given day
       --hide                           Operate on tasks hidden until this day
       --owner                          Operate on tasks with a given owner


  todo.py list
        List all tasks in your todo list.

  todo.py --tag home --tag othertag --group personal list
        List all personl tasks (not in a group with tags 'home' and 'othertag'.

  todo.py --tag cli --group hiveminders edit 3G Implement todo.py
        Move task 3G into the hiveminders group, set its tags to
        "cli", and change the summary.

  todo.py --tag "" 4J
        Delete all tags from task 4J

  todo.py tag 4J home
        Add the tag ``home'' to task 4J

"""


hm_priorities = dict(lowest=1, low=2, normal=3, high=4, highest=5)
hm_priority_names = dict((v,k) for k,v in hm_priorities.items())

# Roughly this translates numbers into base 32...
# would be base 36 except that 0->O, 1->I, S->F, B->P
# to do this with existing encoders, we need to pad rather than replace

rep_digits = string.digits + string.uppercase
compressed_digits = rep_digits.translate(string.maketrans("",""), "01SB") + "____"
map_digits = rep_digits.translate(string.maketrans("01SB", "OIFP"))
loc_to_rep = string.maketrans(compressed_digits, rep_digits)
rep_to_loc = string.maketrans(rep_digits, compressed_digits)
rep_to_map = string.maketrans(rep_digits, map_digits)

def encode_locator(number):
    """Number::RecordLocator encoder"""
    # this *should* be as simple as:
    # return something(locator, 32).translate(rep_to_loc)
    # but while was proposed for 2.5 it doesn't seem to have happened...
    res = []
    while number:
        number, digit = divmod(number, 32)
        res.append(digit)
    return "".join(compressed_digits[digit] for digit in reversed(res))
        

def decode_locator(locator):
    """Number::RecordLocator decoder"""
    # normalize to upper case
    # then translate to the digit subset
    # then compact into 32-contiguous values for int
    return int(locator.upper().translate(rep_to_map).translate(loc_to_rep), 32)

# tests, from Number-RecordLocator-0.001/t/00.load.t
assert encode_locator(1) == "3", "We skip one and zero so should end up with 3 when encoding 1"
assert encode_locator(12354) == 'F44'
assert encode_locator(123456) == '5RL2'
assert decode_locator('5RL2') == 123456
assert decode_locator(encode_locator(123456)) == 123456
assert decode_locator('1234') == decode_locator('I234')
assert decode_locator('10SB') == decode_locator('IOFP')

# encode_locator('A')
# return undef in perl, but clearly should raise here...


# todo.pl was intertwined with globals.
# Here, we split out the config (which wraps operations on the .hiveminder file)
# and the talker (which talks to the server), and don't cross the streams.
class hm_config:
    """Conffile handler"""
    def __init__(self, conffile=None):
        """YAML-based config file with lots of HM-specific bits"""
        if not conffile:
            conffile = os.path.expanduser("~/.hiveminder")
        if os.path.exists(conffile) and os.stat(conffile).st_mode & (stat.S_IROTH | stat.S_IRGRP):
            print "Config file", conffile, "is readable by someone other than you, fixing (to protect your password.)"
            os.chmod(conffile, 0600)            
        self.conffile = conffile
        self.conffilebak = self.conffile + "~"
        # later just derive this from a dict?
        self.config = {}
        self.sid_cookie = None
        self.reload()
    def reload(self):
        """Load the class from the file"""
        if not os.path.exists(self.conffile):
            return # raise?
        self.config = yaml.load(file(self.conffile))

        # if "sid" in self.config:
        #     print "loading cookie:", repr(self.config["sid"])
        #     self.sid_cookie = make_sid_cookie(self.config["sid"], self.config["site"])

        # not that anyone but jesse does this, it's just working around
        # a "localhost.localdomain" setting - which may not even be relevant here:
        if "site" in self.config and "localhost" in self.config["site"]:
            self.config["site"] = self.config["site"].replace("localhost", "127.0.0.1", 1)

    def configured(self):
        """Are we fully configured yet?"""
        return "email" in self.config
    def new_config(self, tester):
        """Initialize config for new users"""
        print """Welcome to todo.py! before we get started, please enter your
Hiveminder username and password so we can access your tasklist.

This information will be stored in""", self.conffile, """should you ever need to
change it."""
        self.config["site"] = self.config.get("site", "http://hiveminder.com")
        while True:
            self.config["email"] = raw_input("First, what's your email address? ")
            self.config["password"] = getpass.getpass("And your password? ")
            if tester():
                break
            print "That combination doesn't seem to be correct. Please try again:"
        # so, this call is redundant in the original too...
        self.save_config()
    def save_config(self):
        """Save config as YAML"""
        old_umask = os.umask(0077)
        outfile = open(self.conffilebak, "w")
        os.chmod(self.conffilebak, 0600)
        # ydump.dumpToFile(outfile, self.config)
        yaml.dump(self.config, outfile)
        outfile.close()
        os.rename(self.conffilebak, self.conffile)
        os.umask(old_umask)    



# part of protocol, really
def make_sid_cookie(sid, uri):
    """Given a sid (from a set-cookie) figure out how to send it back"""
    # sometime near 0.92, port got dropped...
    # uritype, uribody = urllib.splittype(uri)
    # host, path = urllib.splithost(uribody)
    # host, port = urllib.splitnport(host)
    # if port == -1:
    #     port = dict(http=80, https=443)[uritype] # we want to throw here
    cookiename = "JIFTY_SID_HIVEMINDER"
    return "%s=%s" % (cookiename, sid)



class hm_talker:
    """handles the protocol"""
    user_agent = "%s/0.01" % os.path.basename(__file__)
    def __init__(self, conf, debug=False):
        """talk hm protocol to the configured site"""
        self.conf = conf
        self.last_sid = None
        self.debug = debug

    def call(self, verb, **kwargs):
        """Do some yamlrpc"""
        moniker = "fnord"

        posturi = self.conf.config["site"] + "/__jifty/webservices/xml"
        postargs = {"J:A-%s" % moniker: verb}
        for key, val in kwargs.items():
            postargs["J:A:F-%s-%s" % (key, moniker)] = val
        poststr = urllib.urlencode(postargs)
        if self.debug: print "POSTING:", poststr
        if self.debug: print "TO:", posturi
        postio = StringIO.StringIO(poststr)

        respio = StringIO.StringIO()
        ua = pycurl.Curl() # perlish "user agent"
        ua.setopt(pycurl.POST, 1)
        ua.setopt(pycurl.POSTFIELDSIZE, len(poststr))
        ua.setopt(pycurl.READFUNCTION, postio.read)
        ua.setopt(pycurl.WRITEFUNCTION, respio.write)
        ua.setopt(pycurl.URL, posturi)
        if self.debug: ua.setopt(pycurl.VERBOSE, 1)
        ua.setopt(pycurl.USERAGENT, self.user_agent)
        # in theory at least:
        if self.last_sid:
            # print "setting scraped sid_cookie:"
            ua.setopt(pycurl.COOKIE, make_sid_cookie(self.last_sid, None))
        if "sid" in self.conf.config:
            # print "setting stored sid_cookie:"
            ua.setopt(pycurl.COOKIE, make_sid_cookie(self.conf.config["sid"], None))
        ua.setopt(pycurl.COOKIELIST, "") # get cookies *back*
        ua.perform()

        if self.debug: print "SIZE_UPLOAD:", ua.getinfo(pycurl.SIZE_UPLOAD)
        if self.debug: print "CONTENT_LENGTH_UPLOAD:", ua.getinfo(pycurl.CONTENT_LENGTH_UPLOAD)
        http_status = ua.getinfo(pycurl.HTTP_CODE)
        if self.debug: print "HTTP STATUS:", http_status
        rawcookies = ua.getinfo(pycurl.INFO_COOKIELIST)
        self.last_sid = self.extract_sid_value(rawcookies)

        # res = (urllib or curl).post(posturi, postargs)
        res = respio.getvalue()
        if res:
            if self.debug: print "RAW RES:", repr(res)
            # return yaml.load(res)[moniker]
            parsedres = cElementTree.fromstring(res)
            if self.debug: print "RAW XML:", parsedres
            realresult = parsedres.find("result")
            assert realresult.get("moniker") == "fnord", "wrong moniker in response %s" % parsedres.items()
            success = realresult.find("success").text
            if success != "1":
                print "unsuccessful!"
            return success == "1", realresult
        print "OOPS, no response to call"
        return None, None

    def altcall(self, query):
        """Do some jesse hacks"""
        moniker = "fnord"

        posturi = query # self.conf.config["site"] + "/__jifty/webservices/xml"
        #postargs = {"J:A-%s" % moniker: verb}
        #for key, val in kwargs.items():
        #    postargs["J:A:F-%s-%s" % (key, moniker)] = val
        #poststr = urllib.urlencode(postargs)
        #if self.debug: print "POSTING:", poststr
        if self.debug: print "TO:", posturi
        #postio = StringIO.StringIO(poststr)

        respio = StringIO.StringIO()
        ua = pycurl.Curl() # perlish "user agent"
        #ua.setopt(pycurl.POST, 1)
        #ua.setopt(pycurl.POSTFIELDSIZE, len(poststr))
        #ua.setopt(pycurl.READFUNCTION, postio.read)
        ua.setopt(pycurl.WRITEFUNCTION, respio.write)
        ua.setopt(pycurl.URL, posturi)
        if self.debug: ua.setopt(pycurl.VERBOSE, 1)
        ua.setopt(pycurl.USERAGENT, self.user_agent)
        # in theory at least:
        if self.conf.sid_cookie:
            ua.setopt(pycurl.COOKIE, self.conf.sid_cookie)
        ua.setopt(pycurl.COOKIELIST, "") # get cookies *back*
        ua.perform()

        if self.debug: print "SIZE_UPLOAD:", ua.getinfo(pycurl.SIZE_UPLOAD)
        if self.debug: print "CONTENT_LENGTH_UPLOAD:", ua.getinfo(pycurl.CONTENT_LENGTH_UPLOAD)
        http_status = ua.getinfo(pycurl.HTTP_CODE)
        if self.debug: print "HTTP STATUS:", http_status
        rawcookies = ua.getinfo(pycurl.INFO_COOKIELIST)
        self.last_sid = self.extract_sid_value(rawcookies)

        # res = (urllib or curl).post(posturi, postargs)
        res = respio.getvalue()
        if res:
            if self.debug: print "RAW RES:", repr(res)
            if self.debug: print "PRETTY RES:", str(res)
            
            # return yaml.load(res)[moniker]
            parsedres = cElementTree.fromstring(res)
            if self.debug: print "RAW XML:", parsedres
            sys.exit("stop trying")
            realresult = parsedres.find("result")
            assert realresult.get("moniker") == "fnord", "wrong moniker in response %s" % parsedres.items()
            success = realresult.find("success").text
            if success != "1":
                print "unsuccessful!"
            return success == "1", realresult
        print "OOPS, no response to call"
        return None, None

    def extract_sid_value(self, rawcookies):
        """scan the cookies, find the right SID one"""
        # list of tab separated bits
        # http://www.tempesttech.com/cookies/cookietest1.asp
        # ['www.tempesttech.com\tFALSE\t/\tFALSE\t1159865076\tTestCookie\tTest']
        # domain (flag) path (flag) time name value
        for rawcookie in rawcookies:
            domain, flag1, path, flag2, maxtime, name, value = rawcookie.split("\t")
            if self.debug: print "FOUND COOKIE:", name
            if name.startswith("JIFTY_SID_"):
                sid = value.split(";")[0]
                if self.debug: print "FOUND SID:", sid
                return sid

    def do_login(self):
        """Login, get sid/cookie, report if it worked"""
        if "sid" in self.conf.config:
            return True
        ok, res = self.call("Login", 
                            address=self.conf.config["email"], 
                            password=self.conf.config["password"])
        if self.debug: print "call response:", ok, res
        if ok:
            self.conf.config["sid"] = self.last_sid
            self.conf.save_config()
            return True

    # basic marshalling functions
    # these were split out in the perl code, maybe they should
    # be more generic?
    def download_tasks(self, query):
        ok, res = self.call("DownloadTasks",
                            query=query,
                            format="yaml")
        if self.debug: print "download_tasks got:", ok, repr(res)
        # return yaml.load(res["_content"]["result"])
        # print cElementTree.tostring(res)
        if not ok:
            raise Exception(res.find("message").text)
        return yaml.load(res.find("content/result").text)


# generic sub-command argument handler
class subcommands:
    """commands parsing based on a child class"""
    def __init__(self, **kwargs):
        """Construct a subcommand parser with arbitrary options available
        to the subcommands themselves"""
        # check for a less evil way to do this
        self.__dict__.update(kwargs)
    def run(self, args):
        """Actually invoke a given subcommand"""
        cmd = args.pop(0)
        method = getattr(self, "do_" + cmd, self.unknown)
        return method(*args)
    def unknown(self, *extra_args):
        """helper function to display available commands"""
        print "Unknown command: valid commands are"
        print ", ".join(name.replace("do_","",1) for name in dir(self) if name.startswith("do_"))
    def check(self, args):
        """check that the given arguments can be passed to the subcommand"""
        pass
    def do_help(self, *cmds):
        """Display documentation"""
        if cmds:
            cmds = ["do_" + cmd for cmd in cmds]
        else:
            cmds = [name for name in dir(self) if name.startswith("do_")]
        for cmd in cmds:
            doc = getattr(self, cmd).__doc__
            if doc:
                print "%s:" % cmd.replace("do_","",1)
                print "   ", doc

def join_tags(tags):
    return " ".join('"%s"' % tag for tag in tags)

# feature set:
class hm_subcommands(subcommands):
    """todo.pl-compatible subcommands"""
    def map_general_task_args(self):
        args = dict(tags=join_tags(self.options.tag),
                    group_id=self.options.group,
                    owner_id=self.conf.config["email"],
                    priority=self.options.priority,
                    due=self.options.due,
                    starts=self.options.hide)
        for k in args.keys():
            if args[k] == None:
                del args[k]
        return args

    def handle_response(self, resp, success_msg):
        """handle XML response. of course, it's already been tested..."""
        if resp:
            success = resp.find("success").text
            if success == "0":
                error = resp.find("error").text
                sys.exit("failed with %s" % error)
            assert success == "1", "differently successful: %s" % success
            msg = resp.find("message").text
            more_msg = "\n".join(re.findall(">(.*)<", msg))
            print more_msg
            print success_msg
        else:
            raise Exception("Failed to %s: %s" % (success_msg, resp.find("error").text))

    def do_add(self, *summary):
        """create a task"""
        if not summary:
            raise UsageError("Must specify a one-line task description")
        ok, res = self.hm.call("CreateTask",
                               summary=" ".join(summary),
                               **self.map_general_task_args())
        self.handle_response(res, "Created task")
    def do_edit(self, task_id, summary=None):
        ok, res = self.hm.call("UpdateTask",
                               id=decode_locator(task_id),
                               summary = summary,
                               **self.map_general_task_args())
        self.handle_response(res, "Updated task %s" % task_id)

    def do_tag(self, task_id, *new_tags):
        """add tags to an existing task"""
        this_tasks = self.hm.download_tasks("id/%s" % task_id)
        existing_tags = this_tasks[0]["tags"]
        ok, res = self.hm.call("UpdateTask",
                               id=decode_locator(task_id),
                               tags = existing_tags + " " + join_tags(new_tags))
        self.handle_response(res, "Added tags %s to %s" % (", ".join(new_tags), task_id))
    def do_done(self, task_id):
        """Mark task as done"""
        ok, res = self.hm.call("UpdateTask",
                               id=decode_locator(task_id),
                               complete=1)
        self.handle_response(res, "Completed task %s" % task_id)
    do_do = do_done
    def do_del(self, task_id):
        """Delete task by id"""
        ok, res = self.hm.call("DeleteTask",
                               id=decode_locator(task_id))
        self.handle_response(res, "Deleted task %s" % task_id)
    do_rm = do_del
    def do_pending(self):
        pass
    def do_accept(self, task_id):
        pass
    def do_decline(self, task_id):
        pass
    def do_assign(self, task_id, email_addr):
        pass
    def do_requests(self):
        pass
    def do_hide(self, task_id, date):
        """Hide a task until date"""
        ok, res = self.hm.call("UpdateTask", id=decode_locator(task_id), starts=date)
        self.handle_response(res, "Hid task %s until %s" % (task_id, date))
    def do_comment(self, task_id):
        """Add a comment to a task"""
        lines = []
        print "Type your comment now. End with end-of-file or a dot on a line by itself."
        while True:
            s = sys.stdin.readline()
            if not s: # EOF
                break
            if s == ".\n": # dot
                break
            lines.append(s.strip())

        comment = "<br />\n".join(lines)
        ok, res = self.hm.call("UpdateTask", id=decode_locator(task_id), comment=comment)
        self.handle_response(res, "Added comment to task %s" % task_id)

    def do_download(self, filename=None):
        pass
    def do_upload(self, filename):
        """upload braindump tasks from a file"""
        # for now, be lazy and let the caller catch the tracebacks from open
        ok, res = self.hm.call("UploadTasks", content=file(filename).read(), format='sync')
        self.handle_response(res, "Uploaded tasks from %s" % filename)
    def do_list(self):
        """List doable tasks based on options"""
        return self.list_engine("not/complete/starts/before/tomorrow/accepted/but_first/nothing")
    def do_listall(self):
        """List all real tasks based on options"""
        return self.list_engine("not/complete/starts/before/tomorrow/accepted")
    def do_listid(self, task_id):
        """List a single task by id"""
        return self.list_engine("id/%s" % task_id)

    def list_engine(self, default_query):
        """handle listing based on query supplied"""
        query = default_query
        if self.options.tag:
            query = query + "".join("/tag/%s" % tag for tag in self.options.tag)
        for key in ["group", "priority", "due", "owner"]:
            value = getattr(self.options, key)
            if value:
                query = query + "/%s/%s" % (key, value)
        tasks = self.hm.download_tasks(query)
        # print "TASKS:", tasks
        if self.options.task_ids_only:
            for task in tasks:
                print encode_locator(task["id"])
            return
        for owner, my_tasks in itertools.groupby(tasks, operator.itemgetter("owner")):
            print "%s:" % owner
            for prio, my_pri_tasks in itertools.groupby(my_tasks, operator.itemgetter("priority")):
                print "  %s priority:" % hm_priority_names[prio]
                for task in my_pri_tasks:
                    print "    *", task["summary"], "(%s)" % encode_locator(task["id"]), "[%s]" % task["tags"]
                    if task["description"]:
                        print "     -", task["description"].rstrip().replace("\n","\n        ")
                    #print dir(task)
                    #print task
                    # TODO: protocol doesn't *have* last_repeat anymore,
                    #  instead has 'repeat_every': 1, 'repeat_period': 'once', 'repeat_next_create': None,
                    #  'repeat_stacking': 0, 'repeat_days_before_due': 1 (example values)
                    if "last_repeat" in task:
                        subtask = task["last_repeat"]["values"]
                        if int(subtask["depends_on_count"]):
                            print "     ->", subtask["depends_on_count"], subtask["depends_on_ids"], subtask["depends_on_summaries"]
                            print "     ->", subtask["depends_on_count"], encode_locator(subtask["depends_on_ids"]), subtask["depends_on_summaries"]
                        if int(subtask["depended_on_by_count"]):
                            print "     ->", subtask["depended_on_by_count"], subtask["depended_on_by_ids"], subtask["depended_on_by_summaries"]
                            print "     ->", subtask["depended_on_by_count"], encode_locator(subtask["depended_on_by_ids"]), subtask["depended_on_by_summaries"]


    #def do_reconfig(self):
    #    pass
    def do_hack(self, task_id):
        """hack something up from jesse"""
        query = "http://hiveminder.com/=/model/Task/id/%d.json" % decode_locator(task_id)
        print self.hm.altcall(query)
    def do_but_first(self, task_id, depends_on):
        """task_id but-first depends_on"""
        ok, res = self.hm.call("CreateTaskDependency",
                               task_id=decode_locator(task_id),
                               depends_on=decode_locator(depends_on))
        self.handle_response(res, "%s but first %s" % (task_id, depends_on))



if __name__ == "__main__":

    # global options
    parser = optparse.OptionParser(usage=usage)
    parser.disable_interspersed_args()
    parser.add_option("--tag", action="append", default=[])
    parser.add_option("--task-ids-only", action="store_true",
                      help="Only output task ids, for scripting")
    parser.add_option("--group")
    parser.add_option("--priority",
                      choices = hm_priorities.keys() + map(str, hm_priorities.values()))
    parser.add_option("--due")
    parser.add_option("--hide")
    parser.add_option("--owner", default="me")
    parser.add_option("--config")
    parser.add_option("--reconfig", action="store_true")
    parser.add_option("--debug-protocol", action="store_true")
    options, args = parser.parse_args()
    
    subcmds = hm_subcommands()
    subcmds.check(args)

    conf = hm_config(options.config)
    hm = hm_talker(conf, debug=options.debug_protocol)

    subcmds = hm_subcommands(conf=conf, hm=hm, options=options)

    if options.reconfig or not conf.configured():
        conf.new_config(hm.do_login)

    if not hm.do_login():
        # use reconfig?
        sys.exit("Bad username/password; %s --reconfig and try again." % __file__)

    # hack to map priority into names while accepting numbers
    options.priority = hm_priorities.get(options.priority, options.priority)

    if not args:
        args = ["list"]

    subcmds.run(args)
