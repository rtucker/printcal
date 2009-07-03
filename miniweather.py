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
	
	for i in forecast:
		firstword = i.strip().split(' ')[0].strip('.')
		if firstword in daysofweek:
			forecastdayindex = daysofweek.index(firstword)
			dayoffset = forecastdayindex - today
			forecastdatetime = datetime.date.today() + datetime.timedelta(dayoffset)
			hightempnext = lowtempnext = False
			hightemp = lowtemp = pop = False
			for j in i.strip().split(' '):
				if hightempnext:
					hightempnext = False
					hightemp = int(j.strip(',.'))
				elif lowtempnext:
					lowtempnext = False
					lowtemp = int(j.strip(',.'))
				elif j in ['high', 'High']:
					hightempnext = True
				elif j in ['low', 'Low']:
					lowtempnext = True
				elif j[-1] == '%':
					pop = int(j[:-1])

			if hightemp and lowtemp:
				forecastdict[dayoffset] = (hightemp, lowtemp, pop)
			elif hightemp and lowtempcarry:
				if popcarry:
					pop = max(pop, popcarry)
				forecastdict[dayoffset] = (hightemp, lowtempcarry, pop)
				lowtempcarry = False
			elif lowtemp and hightempcarry:
				if popcarry:
					pop = max(pop, popcarry)
				forecastdict[dayoffset] = (hightempcarry, lowtemp, pop)
				hightempcarry = False
			elif lowtemp:
				if dayoffset == 0:
					forecastdict[dayoffset] = (False, lowtemp, pop)
				else:
					lowtempcarry = lowtemp
					popcarry = pop
			elif hightemp:
				hightempcarry = hightemp
				popcarry = pop
	if hightempcarry:
		# handle the "last day" of the forecast, which seems
		# to only show a high temp.  experimental
		forecastdict[dayoffset] = (hightempcarry, False, False)

	return forecastdict

if __name__ == '__main__':
	print `getweather()`

