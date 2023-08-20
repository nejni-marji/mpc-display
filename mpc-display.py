#!/usr/bin/env python3
import os
import sys
import threading
import time

from mpd import MPDClient
import ansiwrap

ESC = '\x1b'
COLOR = '%s[%%sm' % ESC
# CLEAR = ESC + '[H' + ESC + '[2J'



class Player():
	def __init__(self, interactive=False):
		# Set up some debug flags.
		try:
			self.isDebug = os.environ['DEBUG'] in '1 True true yes on'.split(' ')
		except KeyError:
			self.isDebug = False
		if self.isDebug:
			self.debugCounter = {}
			for i in 'display idle meta'.split(' '):
				self.debugCounter[i] = 0
		self.interactive = interactive
		# Initialize object
		self.startup()
		# Initialize data
		self.initializeCache()
		# Start waiting for MPD events
		self.idleThread = threading.Thread(target=self.idleLoop, args=())
		self.idleThread.start()
		# Theoretically, this is where regular updates are drawn to the screen.
		if interactive:
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
		if self.interactive:
			print(ESC + '[?25l', end='')

	def shutdown(self):
		# idleLoop() will get an error, it needs to know we're quitting, or else
		# it will re-raise that error.
		self.quit = True
		# Unhide the cursor.
		if self.interactive:
			print(ESC + '[?25h', end='')
		# Stop idling.
		self.client.noidle()
		# Join with a zero timeout to immediately kill the threads.
		self.idleThread.join(timeout=0)
		if self.interactive:
			self.displayThread.join(timeout=0)
		# Properly disconnect from MPD.
		self.client.close()
		self.client.disconnect()
		if self.interactive:
			exit()

	def pollUser(self):
		try:
			while True:
				time.sleep(60)
		except KeyboardInterrupt:
			self.shutdown()

	def initializeCache(self):
		pass
		# Example of what state we want to store, generally:
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
		if self.isDebug:
			self.debugCounter['meta'] += 1
		# Create a class-internal manifest of the data we actually care about,
		# in the format we actually care about. It's created from a cache of the
		# server state.
		status = self.status
		song   = self.song
		plist  = self.plist

		# Store copies of all the data we care about.
		metadata = {}
		metadata['title']     = self.getProp(song, 'title', 'Unknown')
		metadata['artist']    = self.getProp(song, 'artist', 'Unknown')
		metadata['alb_track'] = int(self.getProp(song, 'track', 0))
		metadata['alb_total'] = self.getAlbumTotal(song)
		metadata['album']     = self.getProp(song, 'album', 'Unknown')
		metadata['state']     = self.getProp(status, 'state', None)
		metadata['lst_track'] = int(self.getProp(status, 'song', -1)) + 1
		metadata['lst_total'] = len(plist)
		metadata['time_curr'] = int(float(self.getProp(status, 'elapsed', 0)))
		metadata['time_song'] = int(float(self.getProp(status, 'duration', 0)))
		metadata['time_pct']  = int(100*metadata['time_curr']/metadata['time_song'])
		try:
			metadata['ersc']  = self.getERSC(status)
		except KeyError:
			metadata['ersc']  = '????'
		metadata['volume']    = int(self.getProp(status, 'volume', -1))
		metadata['xfade']     = int(self.getProp(status, 'xfade', 0))

		# Publish the metadata to shared state.
		self.metadata = metadata

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
		if data['xfade']:
			optStr += ' (x: %i)' % data['xfade']
		# Apply color to each line individually to prevent issues with wrapping
		# later on.
		statusStr = color(timeStr, playColor) + '\n' + color(optStr, playColor)

		# finalize display output
		display = songStr + '\n' + statusStr
		if self.isDebug:
			self.debugCounter['display'] += 1
			# Inject debug data into the now playing text.
			for i in self.debugCounter.keys():
				display += ' %s: %i' % (i[0].upper(), self.debugCounter[i])

		return display

	def wrapTextNP(self, text, width):
		resp = self.wrap(text, width, '')
		return resp

	def getTextPL(self, height):
		# Get playlist size, and current playlist index.
		plSize   = len(self.plist)
		# If the playlist is empty, we can't show anything.
		if plSize == 0:
			return ''
		try:
			# Rare case of not using getProp(), to save on try/except clauses.
			currPos  = int(self.song['pos'])
			hasCurrPos = True
		except KeyError:
			currPos = None
			hasCurrPos = False

		# Get the index we should start displaying from.
		if hasCurrPos:
			head = self.getPlistIndex(height, plSize, currPos)
		else:
			head = 0
		# The tail can't be greater than the length of the playlist.
		tail = min(plSize, head+height)

		resp = []
		for i in range(head, tail):
			# We have already checked that plist isn't empty, so this is
			# probably okay?
			resp.append(self.formatTextPL(self.plist[i], i==currPos))

		resp = '\n'.join(resp)

		return resp

	def wrapTextPL(self, text, width, height):
		if not text:
			return text
		# Calculate indent size from playlist length.
		# TODO: make sure this doesn't fail.
		indent = '.' * (4 + len(self.plist[-1]['pos']))
		# Actually wrap text, but convert it back to an array.
		entries = self.wrap(text, width, indent)
		entries = entries.split('\n')

		# Get current pointer and input length.
		try:
			ptr  = [i for i,v in enumerate(entries) if v.startswith(ESC)][0]
		# It's possible there isn't a current song, so default to 0.
		except IndexError:
			ptr = 0
		plSize = len(entries)
		# Get head/tail given these parameters.
		head = self.getPlistIndex(height, plSize, ptr)
		tail = min(plSize, head+height)

		# Formulate result.
		resp = '\n'.join(entries[head:tail])

		return resp

	def printDisplay(self):
		# Get the size of the terminal, for wrapping, cropping, and padding.
		termSize = os.get_terminal_size()
		tw, th = termSize

		# getTextNP() is perfectly fine, it doesn't need fixing.
		textNP = self.getTextNP()

		# Calculate width, wrap, and calculate height.
		widthNP  = tw # min(tw, 60)
		wrapNP   = self.wrapTextNP(textNP, widthNP)
		heightNP = wrapNP.count('\n') + 1

		finalNP  = wrapNP

		# Calculate width, height, and then wrap.
		heightPL = th - heightNP
		widthPL  = tw # min(tw, 60)
		textPL   = self.getTextPL(heightPL)
		wrapPL   = self.wrapTextPL(textPL, widthPL, heightPL)

		finalPL = wrapPL


		# Start producing the final output.
		text  = '\n'
		# text += '<BEGIN>'
		text += finalNP
		text += '\n'
		text += finalPL
		# text += '<END>'

		# Finally, pad text if necessary.
		paddingHeight = th - text.count('\n')
		padding = '\n' * paddingHeight
		text += padding

		print(text, end='')
		return


	# threaded functions

	def idleLoop(self):
		# List of subsystems that we want to wait for events from.
		subsystems = 'playlist player mixer options'.split()

		while not self.quit:
			# Basically... client.idle() will raise ConnectionError if the
			# thread it's in gets killed. If we're going to quit, we can just
			# break instead, and otherwise the error will be re-raised.
			r = self.client.idle(*subsystems)

			# Run one of several update functions based on what event was
			# triggered.
			# TODO: optimize these functions by bringing them back into
			# idleLoop(), so that we only have to reference updateMetadata()
			# once.
			for i in r:
				{
						'playlist' : self.playlistChange,
						'player'   : self.playerChange,
						'mixer'    : self.mixerChange,
						'options'  : self.optionsChange,
				}[i]()
			if self.isDebug:
				self.debugCounter['idle'] += 1

			# At the end of the idle loop, always print the display. This
			# involves no network operations, so it should be safe to do so.
			# This line may be commented out temporarily for testing purposes,
			# but generally, it *is* meant to be run.
			if self.interactive:
				self.printDisplay()
				time.sleep(0.2)

	def displayLoop(self):
		# This function is meant to redraw the graphical display every so often.
		# This behavior is only useful if self.metadata.time_curr is being
		# updated.
		while not self.quit:

			# If the current song before and after waiting is the same, then we
			# can add the amount of time we waited to the current time.
			if self.getProp(self.status, 'state', 'paused')  == 'play':
				delayTime = 2
				songA = self.getProp(self.song, 'id', None)
				time.sleep(delayTime)
				songB = self.getProp(self.song, 'id', None)
				if songA == songB and self.getProp(self.status, 'state', 'paused') == 'play':
					self.metadata['time_curr'] += delayTime

				# Finally, show the display.
				if not self.quit:
					self.printDisplay()

			else:
				time.sleep(5)
				self.printDisplay()


	# helper functions

	def getProp(self, data, prop, default):
		try:
			return data[prop]
		except KeyError:
			return default

	def getAlbumTotal(self, song):
		# TODO: optimize this by caching the current album, and not updating if
		# the album hasn't changed.
		album = self.getProp(song, 'album', None)
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
		if total <= display:
			index = 0

		else:
			half = int((display-1)/2)
			head = curr-half
			tail = curr+half
			if display%2 == 0: tail += 1

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

		return index

	def wrap(self, text, width, indent):
		entries = text.split('\n')
		new_entries = []
		for i in entries:
			tmp = ansiwrap.wrap(i, width=width, subsequent_indent=indent)
			for j in tmp:
				new_entries.append(j)
		resp = '\n'.join(new_entries)
		return resp

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
