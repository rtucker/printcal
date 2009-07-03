#!/usr/bin/python

import datetime
import time
import weather

daysofweek = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

def getweather():
	forecast = weather.get_forecast('Rochester', 'NY').split('\n')
	forecastdict = {}

	today = time.localtime()[6]

	lowtempcarry = False
	hightempcarry = False
	popcarry = False
	dayconditionscarry = False
	nightconditionscarry = False
	
	for i in forecast:
		firstword = i.strip().split(' ')[0].strip('.')
		if firstword in daysofweek:
			forecastdayindex = daysofweek.index(firstword)
			dayoffset = forecastdayindex - today
			forecastdatetime = datetime.date.today() + datetime.timedelta(dayoffset)
			hightempnext = lowtempnext = False
			hightemp = lowtemp = pop = False
			dayconditions = nightconditions = False
			conditions = i.strip().split('...')[1].split(',')[0].strip()
			if conditions.split(' ')[0] in ['high', 'High', 'low', 'Low']:
				conditions = False
			for j in i.strip().split(' '):
				if hightempnext:
					hightempnext = False
					hightemp = int(j.strip(',.'))
				elif lowtempnext:
					lowtempnext = False
					lowtemp = int(j.strip(',.'))
				elif j in ['high', 'High']:
					hightempnext = True
					dayconditions = conditions
				elif j in ['low', 'Low']:
					lowtempnext = True
					nightconditions = conditions
				elif j[-1] == '%':
					pop = int(j[:-1])

			if hightemp and lowtemp:
				forecastdict[dayoffset] = (hightemp, lowtemp, pop, dayconditions, nightconditions)
			elif hightemp and lowtempcarry:
				if popcarry:
					pop = max(pop, popcarry)
				if nightconditionscarry:
					nightconditions = nightconditionscarry
					nightconditionscarry = False
				forecastdict[dayoffset] = (hightemp, lowtempcarry, pop, dayconditions, nightconditions)
				lowtempcarry = False
			elif lowtemp and hightempcarry:
				if popcarry:
					pop = max(pop, popcarry)
				if dayconditionscarry:
					dayconditions = dayconditionscarry
					dayconditionscarry = False
				forecastdict[dayoffset] = (hightempcarry, lowtemp, pop, dayconditions, nightconditions)
				hightempcarry = False
			elif lowtemp:
				if dayoffset == 0:
					forecastdict[dayoffset] = (False, lowtemp, pop, False, nightconditions)
				else:
					lowtempcarry = lowtemp
					popcarry = pop
					nightconditionscarry = nightconditions
			elif hightemp:
				hightempcarry = hightemp
				dayconditionscarry = dayconditions
				popcarry = pop
	if hightempcarry:
		# handle the "last day" of the forecast, which seems
		# to only show a high temp.  experimental
		forecastdict[dayoffset] = (hightempcarry, False, False, dayconditionscarry, nightconditions)

	return forecastdict

if __name__ == '__main__':
	print `getweather()`

