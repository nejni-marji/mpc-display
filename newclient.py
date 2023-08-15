#!/usr/bin/env python3
import os
import sys
import textwrap
import threading
import time

from mpd import MPDClient
import ansiwrap

ESC = '\x1b'
COLOR = '%s[%%sm' % ESC



# logging.basicConfig(encoding='utf-8', level=logging.INFO)

class Player():
	def __init__(self, interactive=False):
		self.DEBUG = False
		# Initialize object
		self.startup()
		# Initialize data
		self.initializeCache()
		# Start waiting for MPD events
		self.idleThread = threading.Thread(target=self.idleLoop, args=())
		self.idleThread.start()
		# Theoretically, this is where regular updates are drawn to the screen.
		self.displayThread = threading.Thread(target=self.displayLoop, args=())
		self.displayThread.start()
		# If we aren't importing the library, read user input.
		if interactive:
			self.printDisplay()
			self.pollUser()

	def startup(self):
		# Create client object.
		self.client = MPDClient()
		self.client.timeout = 10
		self.client.idletimeout = None
		self.client.connect('localhost', 6600)
		self.quit = False
		# Hide the cursor.
		print(ESC + '[?25l', end='')
		# This was from an era when I thought I might have configurable colors.
		# self.setColors()

	def shutdown(self):
		# idleLoop() will get an error, it needs to know we're quitting, or else
		# it will re-raise that error.
		self.quit = True
		# Unhide the cursor.
		print(ESC + '[?25h', end='')
		# This function isn't defined, actually. It's sad :(
		# self.client.noidle()
		# Join with a zero timeout to immediately kill the threads.
		self.idleThread.join(timeout=0)
		self.displayThread.join(timeout=0)
		# Properly disconnect from MPD.
		self.client.close()
		self.client.disconnect()
		exit()

	def pollUser(self):
		try:
			while True:
				time.sleep(60)
		except KeyboardInterrupt:
			self.shutdown()

		if False:
			pass
			# I'm abandoning the notion of reading user input whatsoever. Using
			# getch() causes prints to the screen to not work right, or
			# something, so it's not worth it.
			# The old code is provided here:

			# try:
			# 	# # Somehow, this is supposed to parse return-separated inputs?
			# 	for line in sys.stdin:
			# 		line = line.rstrip()
			# 	# while True:
			# 	# 	line = getch()
			# 		if line == 'q':
			# 			self.shutdown()
			# 			break
			# 		elif line == '':
			# 			self.printDisplay()
			# 		# elif line == 's':
			# 		# 	print(self.getTextNP())
			# 		# elif line == 'p':
			# 		# 	print(self.getTextPL())
			# 		# elif line == 'u':
			# 		# 	self.initializeCache()
			# except KeyboardInterrupt:
			# 	self.shutdown()
			pass

	def initializeCache(self):
		pass
		# example of what state we want to store, generally:
		# EarthBound 'Battling Organs' OC ReMix
		# Mazedude (#1371/3697)
		# http://ocremix.org
		# |> #14/69: 0:27/2:51, 15%
		# ERsc, 70%
		
		# Log some data
		# TODO: potential bug: non-atomic caching
		self.status = self.client.status()
		self.song   = self.client.currentsong()
		self.plist  = self.client.playlistid()
		# Initialize metadata
		self.updateMetadata()

	def updateMetadata(self):
		# Create a class-internal manifest of the data we actually care about,
		# in the format we actually care about. It's created from a cache of the
		# server state.
		status = self.status
		song   = self.song
		plist  = self.plist
		# Store copies of all the data we care about.
		# TODO: handle key errors
		# TODO: optimize the getAlbumTotal() call
		times = [int(i) for i in status['time'].split(':')]
		self.metadata = {
				'title'      : song['title'],
				'artist'     : song['artist'],
				'alb_track'  : int(song['track']),
				'alb_total'  : int(self.getAlbumTotal(song)),
				'album'      : song['album'],
				'state'      : status['state'],
				'lst_track'  : int(status['song']) + 1,
				'lst_total'  : len(plist),
				'time_curr'  : int(times[0]),
				'time_song'  : int(times[1]),
				'time_pct'   : int(100*times[0]/times[1]),
				'ersc'       : self.getERSC(status),
				'volume'     : int(status['volume']),
		}
		self.album = song['album']

	def getTextNP(self):
		data = self.metadata
		color = self.color

		# The general descriptor for how we're formatting this is in
		# initializeCache().

		# SONG: title, artist, album progress
		songStr = '{}\n{} ({})'.format(
				color(data['title'], '1;34'),
				color(data['artist'], '1;36'),
				color('#%i/%i' % (data['alb_track'], data['alb_total']), '32'),
				)

		# STATUS: state, playlist progress, time, playback settings, volume
		playColor = '32' if data['state'] == 'play' else '31'
		timeStr = '{} {}/{}: {}/{}, {}%'.format(
				'|>' if data['state'] == 'play' else '||',
				data['lst_track'], data['lst_total'],
				'%i:%02i' % divmod(data['time_curr'], 60),
				'%i:%02i' % divmod(data['time_song'], 60),
				data['time_pct'],
				)
		optStr = '{}, {}%'.format(
				data['ersc'], data['volume'],
				)
		# Apply color to each line individually to prevent issues with wrapping
		# later on.
		statusStr = color(timeStr, playColor) + '\n' + color(optStr, playColor)

		# finalize display output
		display = songStr + '\n' + statusStr

		return display

	def getTextPL(self):
		# This variable has to account for the readline at the bottom.
		NP_HEIGHT = 4

		# Get display plHeight, playlist size, and current playlist index.
		plHeight = os.get_terminal_size()[1] - NP_HEIGHT
		plSize   = len(self.plist)
		currPos  = int(self.song['pos'])

		# Get the index we should start displaying from.
		head = self.getPlistIndex(plHeight, plSize, currPos)
		# The tail can't be greater than the length of the playlist.
		tail = min(plSize, head+plHeight)

		resp = []
		for i in range(head, tail):
			resp.append(self.formatTextPL(self.plist[i], i==currPos))

		# Join the lines and pad the end with newlines, because we don't clear
		# the screen first.
		padding = '\n' * (plHeight - len(resp))
		resp = '\n'.join(resp) + padding

		# TODO: add text wrapping!
		resp = self.wrapTextPL(resp)

		return resp

	def wrapTextPL(self, text):
		width = os.get_terminal_size()[0]
		# TODO: this is a debug command
		width = min(width, 50)

		indent = '.' * (4 + len(self.plist[-1]['pos']))
		entries = text.split('\n')
		new_entries = []
		for i in entries:
			tmp = textwrap.wrap(i, width=width, subsequent_indent=indent)
			for j in tmp:
				new_entries.append(j)

		# current pointer, input/output height, head/tail of display
		ptr  = [i for i,v in enumerate(new_entries) if v.startswith(ESC)][0]
		inH  = len(entries)
		outH = len(new_entries)
		head = self.getPlistIndex(inH, outH, ptr)
		tail = min(outH, head+inH)

		resp = []
		for i in range(head, tail):
			resp.append(new_entries[i])

		resp = '\n'.join(resp)

		return resp

	def printDisplay(self):
		text  = '\n'
		text += self.getTextNP()
		text += '\n'
		text += self.getTextPL()
		print(text, end='')


	# threaded functions

	def idleLoop(self):
		# List of subsystems that we want to wait for events from.
		subsystems = 'playlist player mixer options'.split()

		while not self.quit:
			# Basically... client.idle() will raise ConnectionError if the
			# thread it's in gets killed. If we're going to quit, we can just
			# break instead, and otherwise the error will be re-raised.
			try:
				r = self.client.idle(*subsystems)
			finally:
				if self.quit:
					break

			# Run one of several update functions based on what event was
			# triggered.
			# TODO: optimize these functions by bringing them back into
			# idleLoop(), so that we only have to reference updateMetadata() once.
			for i in r:
				{
						'playlist' : self.playlistChange,
						'player'   : self.playerChange,
						'mixer'    : self.mixerChange,
						'options'  : self.optionsChange,
				}[i]()

			# At the end of the idle loop, always print the display. This
			# involves no network operations, so it should be safe to do so.
			# This line may be commented out temporarily for testing purposes,
			# but generally, it *is* meant to be run.
			self.printDisplay()

	def displayLoop(self):
		# This function is meant to redraw the graphical display every so often.
		# This behavior is only useful if self.metadata.time_curr is being
		# updated.
		while not self.quit:

			# If the current song before and after waiting is the same, then we
			# can add the amount of time we waited to the current time.
			if self.status['state'] == 'play':
				delayTime = 2
				songA = self.song['id']
				time.sleep(delayTime)
				songB = self.song['id']
				if songA == songB and self.status['state'] == 'play':
					self.metadata['time_curr'] += delayTime

				# Finally, show the display.
				if not self.quit:
					self.printDisplay()

			else:
				# r = self.client.idle('player')
				time.sleep(5)
				pass



	# helper functions

	def getAlbumTotal(self, song):
		# TODO: optimize this by caching the current album, and not updating if
		# the album hasn't changed.
		album = song['album']
		return len(self.client.find('album', album))

	def getERSC(self, status):
		keys = ['repeat', 'random', 'single', 'consume']
		vals = list('ersc')
		for i in range(len(keys)):
			if status[keys[i]] == '1':
				vals[i] = vals[i].upper()
		return ''.join(vals)

	def formatTextPL(self, song, curr=False):
		# TODO: reorganize this function
		num = int(song['pos']) + 1
		title = song['title']
		numstr = '%%%ii' % len(self.plist[-1]['pos']) % num
		resp = '  %s  %s' % (numstr, title)
		if curr:
			resp = self.color('>' + resp[1:], '1')
		return resp

	def getPlistIndex(self, display, total, curr):
		# TODO: reorganize this function
		# This function is magic.
		if total <= display:
			index = 0

		else:
			half = int((display-1)/2)
			head = curr-half
			tail = curr+half
			if display%2 == 0: tail += 1

			if self.DEBUG: print('h: %i, t: %i' % (head, tail))
			# Values are invalid if the start of the list is before 0, or if the
			# end of the list is after the end of the list.
			headError = head < 0
			tailError = tail >= total
			# This shouldn't happen, but just in case?
			if headError and tailError:
				raise Exception
			# Handle both types of errors separately.
			elif headError:
				index = 0
			elif tailError:
				index = total - display
			else:
				index = head

		if self.DEBUG: print('he: %s, te: %s, i: %i' % (headError, tailError, index))
		return index

	def color(self, s, ansi):
		return COLOR % ansi + s + COLOR % 0


	# mutator helper functions

	def playlistChange(self):
		self.plist = self.client.playlistid()
		self.updateMetadata()
		pass

	def playerChange(self):
		self.status = self.client.status()
		self.song   = self.client.currentsong()
		self.updateMetadata()
		pass

	def mixerChange(self):
		self.status = self.client.status()
		self.updateMetadata()
		pass

	def optionsChange(self):
		self.status = self.client.status()
		self.updateMetadata()
		pass



if __name__ == '__main__':
	x = Player(interactive=True)
