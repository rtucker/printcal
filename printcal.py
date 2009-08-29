#!/usr/bin/python -W ignore

# script based off of gcalcli to print a daily schedule from the calendar
# ryan tucker, 2009/03/25

import cups
from datetime import *
from dateutil.tz import *
from dateutil.parser import *
import gcalcli
import miniweather
import os
import string
import sys
import tempfile

maxcolumns = 77
maxrows = 65
days = 45

cfg = gcalcli.LoadConfig('~/.gcalclirc')
usr = gcalcli.GetConfig(cfg, 'user', '')
pwd = gcalcli.GetConfig(cfg, 'pw', '') 
access = gcalcli.GetConfig(cfg, 'cals', 'all')
details = True

timeFormat = '%l:%M'
dayFormat = '\n%a %b %d'

weather = miniweather.getweather()

today = datetime.now(tzlocal()).replace(hour=0, minute=0, second=0, microsecond=0)
tomorrow = today + timedelta(days=1)
dayafter = tomorrow + timedelta(days=1)

todaywx = (today, weather[0])
tomorrowwx = (tomorrow, weather[1])
dayafterwx = (dayafter, weather[2])

gcal = gcalcli.GoogleCalendar(username=usr, password=pwd, access=access, details=details)

eventList = gcal._SearchForCalEvents(today, today + gcalcli.timedelta(days=30), today, None)

outrows = []

day = ''
wx = ''

def get_todo_by_day(date='today'):
    # Prints a todo list by date, from todo.py.
    # Should just be able to import it, but arrrgh
    todopath = '/home/rtucker/bin/todo.py'
    todolist = os.popen(todopath + ' --due %s list' % date).readlines()
    if len(todolist) > 0:
        # remove the first line, since it's boilerplate
        return todolist[1:]
    else:
        # empty list
        return todolist

def get_cal_by_day(gcal, date=datetime.now(tzlocal()).replace(hour=0, minute=0,
                   second=0, microsecond=0)):
    """Returns a gcalcli eventlist for a given date.  Requires a
       gcalcli.GoogleCalendar instance (gcal), accepts datetime object (date)
    """
    return gcal._SearchForCalEvents(start=date, end=date+timedelta(days=1),
                                    defaultDateTime=date, searchText=None)

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
            yield todolist[1:]
        else:
            # empty list
            yield todolist

def make_weather_string(wxtuple):
    (hightemp, lowtemp, pop, dayconditions, nightconditions) = wxtuple
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

    return string.join(output, ', ')

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

        yield outdict

def main():
    for event in eventList:
        eventStartDateTime = parse(event.when[0].start_time, default=today).astimezone(tzlocal())
        if eventStartDateTime < today:
            continue
        tmpDayStr = eventStartDateTime.strftime(dayFormat)
        meridiem = eventStartDateTime.strftime('%p').lower()
        tmpTimeStr = eventStartDateTime.strftime(timeFormat) + meridiem

        eventstring = '%-7s  %s' % (tmpTimeStr, event.title.text)

        try:
            tmptodaywx = weather[(eventStartDateTime - today).days]
            if False in tmptodaywx:
                tmpwxstr = ''
                for wxelement in tmptodaywx[0:3]:
                    if not wxelement:
                        tmpwxstr += ' NA'
                    else:
                        tmpwxstr += '%3i' % wxelement
                tmpwxstr += '%'
            else:
                tmpwxstr = '%3i%3i%3i%%' % tmptodaywx
        except KeyError:
            tmpwxstr = wx = None

        if event.when[0].end_time:
            eventEndDateTime = parse(event.when[0].end_time,
                default=today).astimezone(tzlocal())
            diffDateTime = (eventEndDateTime - eventStartDateTime)
            lengthstring = 'Len: %s' % diffDateTime.__str__()[:-3]
            if lengthstring == 'Len: 1 day, 0:00':
                lengthstring = ''
        else: lengthstring = ''

        if event.where[0].value_string:
            locationstring = 'At: %s' % event.where[0].value_string
        else: locationstring = ''

        if event.content.text:
            contentstring = 'Content: %s' % event.content.text.strip()
        else: contentstring = ''

        # assemble some output!
        outblock = ''
        indent = ' '*11

        if (tmpDayStr != day):
            outstring = tmpDayStr + ' ' + eventstring
            day = tmpDayStr
        elif (tmpwxstr != wx):
            outstring = tmpwxstr + ' ' + eventstring
            wx = tmpwxstr
        else:
            outstring = indent + eventstring

        if lengthstring:
            if len(outstring) + len(lengthstring) < maxcolumns:
                outstring += ', ' + lengthstring
            else:
                # we've wrapped!
                outblock += outstring + '\n'
                if (tmpwxstr != wx):
                    outstring = tmpwxstr + indent + ' ' + lengthstring
                    wx = tmpwxstr
                else:
                    outstring = indent*2 + lengthstring
        if locationstring:
            if len(outstring) + len(locationstring) < maxcolumns:
                outstring += ', ' + locationstring
            else:
                outblock += outstring + '\n'
                if (tmpwxstr != wx):
                    outstring = tmpwxstr + indent + ' ' + locationstring
                    wx = tmpwxstr
                else:
                    outstring = indent*2 + locationstring
        if contentstring:
            # this always gets its own line
            outblock += outstring + '\n'
            if (tmpwxstr != wx):
                outstring = tmpwxstr + indent + ' ' + contentstring
            else:
                outblock += indent*2 + contentstring
            outstring = ''
        if outstring:
            # flush the buffer, if you will
            outblock += outstring

        outrows.append(outblock)

    curline = 1
    tmpfile = tempfile.NamedTemporaryFile()

    # grab a couple days of to-do lists...
    for i in ['overdue', todaywx, tomorrowwx, dayafterwx]:
        if i == 'overdue':
            rawdate = 'before/today'
            dayofweek = 'OVERDUE'
            header = '*** OVERDUE ***\n'
        else:
            day = i[0]
            wx = i[1]
            rawdate = day.strftime('%Y/%m/%d')    # 2009/07/01
            dayofweek = day.strftime('%A')        # Wednesday
            header = dayofweek + ': %s\n' % make_weather_string(wx)
        if curline < maxrows:
            todo = get_todo_by_day(rawdate)
            if todo:
                tmpfile.write(header)
                curline += 1
                for j in todo:
                    if curline < maxrows:
                        if (len(j)/maxcolumns > 0):
                            curline += (len(j)/maxcolumns)
                        else:
                            curline += 1
                        tmpfile.write(j)

    for i in outrows:
        if curline > maxrows: break

        for j in string.split(i, '\n'):
            if (len(j)/maxcolumns > 0):
                # it's gonna wrap
                curline += (len(j)/maxcolumns)
            curline += 1
            if curline < maxrows:
                try:
                    tmpfile.write(j + '\n')
                except UnicodeEncodeError:
                    tmpfile.write("FAIL: " + `j` + '\n')
    
    # Printing time!
    tmpfile.flush()
    tmpfile.seek(0)
    if len(sys.argv) > 1:
        if sys.argv[1] == 'console':
            print tmpfile.read()
            tmpfile.close()
            sys.exit(0)

    printer = cups.Connection()
    printer.printFile('samsung', tmpfile.name, "Ryan's Daily Schedule", {})
    tmpfile.close()

if __name__ == '__main__': main()

