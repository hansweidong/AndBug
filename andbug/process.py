## Copyright 2011, Scott W. Dunlop <swdunlop@gmail.com> All rights reserved.
##
## Redistribution and use in source and binary forms, with or without 
## modification, are permitted provided that the following conditions are 
## met:
## 
##    1. Redistributions of source code must retain the above copyright 
##       notice, this list of conditions and the following disclaimer.
## 
##    2. Redistributions in binary form must reproduce the above copyright 
##       notice, this list of conditions and the following disclaimer in the
##       documentation and/or other materials provided with the distribution.
## 
## THIS SOFTWARE IS PROVIDED BY SCOTT DUNLOP 'AS IS' AND ANY EXPRESS OR 
## IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
## OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. 
## IN NO EVENT SHALL SCOTT DUNLOP OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
## INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES 
## (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR 
## SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) 
## HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, 
## STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
## ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE 
## POSSIBILITY OF SUCH DAMAGE.

from threading import Thread
from andbug.jdwp import JdwpBuffer

class HandshakeError(Exception):
	def __init__(self):
		Error.__init__(
			self, 'handshake error, received message did not match'
		)

class ProtocolError(Exception):
	pass

HANDSHAKE_MSG = 'JDWP-Handshake'
HEADER_FORMAT = '4412'
IDSZ_REQ = (
	'\x00\x00\x00\x0B' # Length
	'\x00\x00\x00\x01' # Identifier
	'\x00'             # Flags
	'\x01\x07'         # Command 1:7
)

class Process(Thread):
	'''
	The JDWP Processor is a thread which abstracts the asynchronous JDWP protocol
	into a more synchronous one.  The thread will listen for packets using the
	supplied read function, and transmit them using the write function.  

	Requests are sent by the processor using the calling thread, with a mutex 
	used to protect the write function from concurrent access.  The requesting
	thread is then blocked waiting on a response from the processor thread.

	The Processor will repeatedly use the read function to receive packets, which
	will be dispatched based on whether they are responses to a previous request,
	or events.  Responses to requests will cause the requesting thread to be
	unblocked, thus simulating a synchronous request.
	'''

	def __init__(self, read, write):
		Thread.__init__(self)
		self.xmitbuf = JdwpBuffer()
		self.recvbuf = JdwpBuffer()
		self.read = read
		self.write = write
		self.initialized = False
		self.nextId = 3

	###################################################### INITIALIZATION STEPS
	
	def writeIdSzReq(self):
		return self.write(IDSZ_REQ)

	def readIdSzRes(self):
		head = self.readHeader();
		if head[0] != 20:
			raise ProtocolError('expected size of an idsize response')
		if head[2] != 0x80:
			raise ProtocolError('expected first server message to be a response')
		if head[1] != 1:
			raise ProtocolError('expected first server message to be 1')

		sizes = self.recvbuf.unpack( 'iiiii', self.read(20) )
		self.recvbuf.config(*sizes)
		self.xmitbuf.config(*sizes)
		return None

	def readHandshake(self):
		data = self.read(len(HANDSHAKE_MSG))
		if data != HANDSHAKE_MSG:
			raise HandshakeError()
		
	def writeHandshake(self):
		return self.write(HANDSHAKE_MSG)

	############################################### READING / PROCESSING PACKETS
	
	def readHeader(self):
		'reads a header and returns [size, id, flags, event]'
		head = self.read(11)
		data = self.recvbuf.unpack(HEADER_FORMAT, head)
		data[0] -= 11
		return data
	
	def readContent(self, size):
		return self.read(size)

	####################################################### TRANSMITTING PACKETS
	
	def writeHeader(self, size, flags, event):
		'used internally by the processor'

		ident = self.nextId
		self.nextId += 2		
		size += 11
		data = self.xmitbuf.pack(
			HEADER_FORMAT, size, ident, flags, event
		)
		self.write(data)
		return ident

	def writeContent(self, content):
		'sends a response or request'

		code = content.code
		flags = content.flags
		self.xmitbuf.preparePack()
		content.packTo(self.xmitbuf)
		data = self.xmitbuf.data()
		size = len(data)
		self.writeHeader( size, flags, code )
		return self.write(data)

	################################################################# THREAD API
	
	def start(self):
		'performs handshaking and solicits configuration information'

		if not self.initialized:
			self.writeHandshake()
			self.readHandshake()
			self.writeIdSzReq()
			self.readIdSzRes()
			self.initialized = True
			Thread.start(self)
		return None

	def run(self):
		pass
		#TODO while True:
		#TODO 	self.processPacket(*self.readPacket())
	
class Element(object):
	'''
	Elements, such as messages or entries found in messages, can be packed to
	a JDWP buffer, or unpacked from them.
	'''

	def __init__(self):
		pass

	def packTo(self, buf):
		'packs data associated with this element into the buffer'
		pass

	@classmethod
	def unpackFrom(impl, buf):
		'creates a new instance from the contents of the buffer'
		return impl()
		#TEST
 
class Content(Element):
	'''
	A JDWP packet consists of a Header and an optional Content.  Descendants
	of the Content class do not manage the Header portion -- the Processor will
	derive this prior to unpackFrom and after packTo.
	'''

	def __init__(self):
		Element.__init__(self)
		
	@property
	def code(self):
		'''
		specifies either the content of the cmdset and cmd fields, or the 
		response code
		'''
		return self.CODE

	@property
	def flags(self):
		'returns the static FLAGS associated with this Content type'
		return self.FLAGS

class Response(Content):
	'''
	Expresses a response to a JDWP request; shared base of Failure and Success
	'''
	FLAGS = 0x80
	pass #TODO

class Failure(Response):
	'''
	Failures are error responses to a request; each individual Failure class
	should specify its associated CODE, as specified in JVMDI.
	'''
	pass #TODO

class Success(Response):
	'''
	Successes are responses to a request; since the Processor cannot determine
	the correct class of a Success without contextual information about the
	Request, each Request should have a associated unpackSuccess function.
	'''
	CODE = 0x0000

class Request(Content):
	'''
	Requests made from the debugger to the process should have an associated
	SUCCESS class that supports the unpackFrom class method.
	'''
	FLAGS = 0x00
	SUCCESS = None

	def unpackSuccessFrom(self, buf):
		return self.SUCCESS.unpackFrom(buf)
		#TEST

class Event(Request):
	'''
	Events are a special case of Request, where the debugger recieves a 
	"request" from the process.  Events are unusual, in that a number of
	of them are collected into a single request, and that no response is
	expected by the process from the debugger.
	'''
	pass #TODO