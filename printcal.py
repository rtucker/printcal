#!/usr/bin/python -W ignore

# Script based off of gcalcli to print a daily schedule from the calendar
# Ryan Tucker <rtucker@gmail.com>

import cups
from datetime import *
from dateutil.tz import *
from dateutil.parser import *
import gcalcli
import miniweather
import os
import random
import re
import shelve
import string
import sys
import tempfile
import textwrap
import time

# build translation ascii table
asciitable = string.maketrans(''.join(chr(a) for a in xrange(127,256)), '?'*129)

def get_cal_by_day(gcal, date=datetime.now(tzlocal()).replace(hour=0, minute=0,
                   second=0, microsecond=0)):
    """Returns a gcalcli eventlist for a given date.  Requires a
       gcalcli.GoogleCalendar instance (gcal), accepts datetime object (date)
    """
    out = []
    for i in gcal._SearchForCalEvents(start=date, end=date+timedelta(days=1),
                 defaultDateTime=date, searchText=None):
        eventStartDateTime = parse(i.when[0].start_time, default=date).astimezone(tzlocal())
        if eventStartDateTime.strftime('%j') == date.strftime('%j'):
            out.append(i)
    return out

def iter_weather(city='Washington',state='DC'):
    """Returns an iterator giving weather for today, tomorrow, and the
       day after"""
    weather = miniweather.getweather(city=city,state=state)

    for i in weather.keys():
        yield weather[i]

def iter_calendar(gcal, start=datetime.now(tzlocal()).replace(hour=0, minute=0,
                   second=0, microsecond=0),
                  end=datetime.fromtimestamp(2**31-86400, tz=tzlocal())):
    """Returns an iterator that spits out a day of calendar stuff per
       iteration.  Takes a gcalcli.GoogleCalendar instance as gcal.  Accepts
       a datetime as start and end.  Defaults to today, and never."""

    pointer = start

    while pointer < end:
        result = get_cal_by_day(gcal=gcal, date=pointer)
        pointer += timedelta(days=1)
        yield result

def iter_todo(path, start=datetime.now(tzlocal()).replace(hour=0, minute=0,
                   second=0, microsecond=0),
              end=datetime.fromtimestamp(2**31-86400, tz=tzlocal()),
              firstoverdue=False):
    """Returns an iterator that spits a day of to-do list stuff per
       iteration.  Takes a path to todo.py or todo.pl or something as
       path, and accepts a datetime as start and end.  Defaults to today
       and never.  Also accepts firstoverdue as boolean (False); if
       true, the first iteration spits out things due before today
       (that is, overdue things.)
    """

    pointer = start

    while pointer < end:
        if firstoverdue:
            search = 'before/today'
            firstoverdue = False
        else:
            search = pointer.strftime('%Y/%m/%d')
            pointer += timedelta(days=1)

        todolist = os.popen(path + ' --due %s list' % search).readlines()
        if len(todolist) > 0:
            # remove the first line, since it's boilerplate
            out = []
            for i in todolist[1:]:
                line = re.sub(' \[.*\]$', '', i.strip())
                if line.startswith('-'):
                    out.append('   ' + line)
                elif line.startswith('*'):
                    out.append(' ' + line)
                else:
                    out.append(line)
            yield out
        else:
            # empty list
            yield []

def iter_random_todo(path):
    """Returns iterator of random, no-due-date todo list items"""

    # cache is a dict:  {'taskid': (todoitem object, timestamp)}
    cache = shelve.open('/tmp/printcalcache.shelve', writeback=True)
    # expire stuff
    for i in cache.keys():
        item, ts = cache[i]
        if ts+(15*24*60*60) < time.time():
            # more than 15 days old; purge.
            del cache[i]

    todoids = os.popen(path + ' --due after/forever --task-ids-only').readlines()
    if len(todoids) > 0:
        random.shuffle(todoids)
        for i in todoids:
            if i in cache:
                todoitem, ts = cache[i]
            else: 
                todoitem = os.popen(path + ' listid ' + i).readlines()[2]
                cache[i] = (todoitem, time.time())

            line = re.sub(' \[.*\]$', '', todoitem.strip())
            if line.startswith('*'):
                yield line

def iter_days(gcal, start=datetime.now(tzlocal()).replace(hour=0, minute=0,
              second=0, microsecond=0),
              end=datetime.fromtimestamp(2**31-86400, tz=tzlocal()),
              firstoverdue=False, weather=('Rochester', 'NY'), path=None):
    """Returns an iterator producing a daily dictionary of useful data,
       including 'calendar', 'todo', 'weather'.
       Requires gcalcli.GoogleCalendar instance as gcal, accepts path as
       a path to todo.py or todo.pl (default: no todo list), accepts start
       and end as datetimes (assumes today and never), accepts firstoverdue
       (if True, the first run returns only a 'todo' with things due before
       today), and accepts weather as a tuple of (City, State)."""

    cal = iter_calendar(gcal, start=start, end=end)
    if path:
        todo = iter_todo(path=path, start=start, end=end,
                         firstoverdue=firstoverdue)
    else:
        todo = None
    wx = iter_weather(city=weather[0], state=weather[1])

    counter = 0
    pointer = start

    while True:
        if firstoverdue:
            firstoverdue = False
            yield {'day': -1, 'todo': todo.next()}
        
        outdict = {'day': counter, 'datetime': pointer}

        for i in [cal, todo, wx]:
            if i:
                try:
                    name = i.gi_code.co_name.split('_')[1]
                    result = i.next()
                    outdict[name] = result
                except StopIteration:
                    pass

        counter += 1
        pointer += timedelta(days=1)

        if pointer > end:
            return
        else:
            yield outdict

def format_day_text(daydict, order=['weather', 'calendar', 'todo']):
    """Formats a dictionary containing daystuff into a pretty block of
    text.  Requires daydict (the dictionary of day stuff), accepts
    order (a list of keys, in order of output preference)."""

    out = []
    if daydict.has_key('datetime'):
        out.append(daydict['datetime'].strftime('%A, %B %d (Day %j, week %W)'))

    for i in order:
        if daydict.has_key(i):
            tmp = eval('format_day_sub_%s(daydict["%s"])' % (i, i))
            if daydict['day'] < 0 and i is 'todo' and len(tmp) > 0:
                out.append('*** OVERDUE TODO LIST ITEMS ***')
            out.extend(tmp)

    return out

def get_timestring(eventtime):
    """Take an event.when time and return a good-looking formatted time"""
    eventDateTime = parse(eventtime,
        default=datetime.now(tzlocal()).replace(hour=0, minute=0,
        second=0, microsecond=0)).astimezone(tzlocal())
    meridiem = eventDateTime.strftime('%p').lower()
    return eventDateTime.strftime('%l:%M') + meridiem

def format_day_sub_calendar(row):
    """Formats a list of CalendarEventEntry objects into a list of pretty
    output strings."""

    out = []

    for event in row:
        startTimeStr = get_timestring(event.when[0].start_time)
        endTimeStr = get_timestring(event.when[0].end_time)

        if event.where[0].value_string:
            location = ' (%s)' % event.where[0].value_string
        else:
            location = ''

        if startTimeStr == endTimeStr == '12:00am':
            out.append('All day: %s' % (event.title.text + location))
        elif startTimeStr == endTimeStr:
            out.append('        %-7s  %s' % (startTimeStr,
                                             event.title.text + location))
        else:
            out.append('%-7s-%-7s  %s' % (startTimeStr, endTimeStr,
                                          event.title.text + location))

    return out

def format_day_sub_todo(row):
    """Formats a list of todo list items into... well, I don't do much."""
    return row

def format_day_sub_weather(row):
    """Pretties up the weather."""
    (hightemp, lowtemp, pop, dayconditions, nightconditions) = row
    output = []
    if dayconditions:
        output.append(dayconditions)
    if hightemp:
        output.append('High %i' % hightemp)
    if nightconditions:
        output.append('At night, %s' % nightconditions)
    if lowtemp:
        output.append('Low %i' % lowtemp)
    if pop:
        output.append('(POP: %i%%)' % pop)

    return [', '.join(output)]

def iter_text_days(gcal, start=datetime.now(tzlocal()).replace(hour=0,
                               minute=0, second=0, microsecond=0),
              end=datetime.fromtimestamp(2**31-86400, tz=tzlocal()),
              enddelta=None,
              firstoverdue=False, weather=('Rochester', 'NY'), path=None,
              order=['weather', 'calendar', 'todo'], maxwidth=74):
    """Yields a list of rows of length < maxwidth.  Arguments are the
    union of iter_days and format_day_text, basically."""

    if enddelta:
        end = start+timedelta(days=enddelta)

    iter = iter_days(gcal, start=start, end=end, firstoverdue=firstoverdue,
                     weather=weather, path=path)

    for i in iter:
        out = []
        for j in format_day_text(i, order=order):
            out.extend(textwrap.wrap(j, maxwidth))
        yield out

def main():
    cfg = gcalcli.LoadConfig('~/.gcalclirc')
    usr = gcalcli.GetConfig(cfg, 'user', '')
    pwd = gcalcli.GetConfig(cfg, 'pw', '')
    access = gcalcli.GetConfig(cfg, 'cals', 'all')
    details = True

    cookiefile = '/home/rtucker/dev/printcal/oblique_strategies.txt'
    maxlength = 63
    maxwidth = 78

    gcal = gcalcli.GoogleCalendar(username=usr, password=pwd, access=access, details=details)

    footer = ['']

    cookie = random.sample(open(cookiefile, 'r').readlines(), 1)[0].strip()

    todaydatetime = time.strftime('%m/%d at %H:%M')

    printcalrevdate = time.strftime('%Y.%m.%d.%H%M',
                      time.localtime(os.stat(sys.argv[0]).st_mtime))

    myhostname = os.uname()[1].split('.')[0]

    footer.extend(textwrap.wrap(cookie, maxwidth))
    footer.append('Schedule printed %s: printcal (%s) on %s' % (
               todaydatetime, printcalrevdate, myhostname))

    remaining = maxlength - len(footer)
    out = []

    iter = iter_text_days(gcal, firstoverdue=True, maxwidth=maxwidth,
                          enddelta=7,
                          path='/home/rtucker/dev/printcal/todo.py')

    while remaining > 0:
        try:
            row = iter.next()
        except StopIteration:
            break
        if len(row) > 1:
            row.append('')  # to get a nice blank line
            remaining -= len(row)
            if remaining > 0:
                for i in row:
                    i = i.translate(asciitable)
                    if len(out) is ((maxlength/3)-2):
                        # pad the line with dots if it's a good fold point
                        out.append(str('{0:.<%i}' % maxwidth).format(i))
                    else:
                        out.append(i)

    # reset remaining
    remaining = maxlength - len(footer) - len(out)

    if remaining > 2:
        out.append('Todo List Items of the Future...')
        remaining -= 1
        todoiter = iter_random_todo(path='/home/rtucker/dev/printcal/todo.py')

        while remaining > 0:
            try:
                row = todoiter.next().translate(asciitable)
                if len(row) < maxwidth:
                    remaining -= 1
                    out.append(row)
            except StopIteration:
                remaining = 0

    out.extend(footer)

    if len(sys.argv) > 1:
        if sys.argv[1] == 'console':
            print '\n'.join(out)
            sys.exit(0)

    printer = cups.Connection()
    printername = printer.getDefault()

    tmpfile = tempfile.NamedTemporaryFile()
    tmpfile.write('\n'.join(out))
    tmpfile.flush()
    tmpfile.seek(0)
    printer.printFile(printername, tmpfile.name, "Ryan's Daily Schedule", {})
    tmpfile.close()

if __name__ == '__main__': main()

