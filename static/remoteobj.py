#!/usr/bin/env python
# remoteobj v0.3, now with speed hax!
# Also, I just noticed that this will get wrecked by recursive sets/lists/dicts;
# v0.4 should .pack everything as tuples or something.
import marshal
import struct
import socket
import sys, exceptions, errno, traceback
from types import CodeType
from os import urandom
from hashlib import sha1

DEBUG = False

class Proxy(object):
  def __init__(self, conn, info):
    object.__setattr__(self, '_proxyconn', conn)
    object.__setattr__(self, '_proxyinfo', info)
    object.__setattr__(self, '_proxyhash', None)
  def __getattribute__(self, attr):
    t = object.__getattribute__(self, '_proxyinfo').getattr(attr)
    if t:
      return Proxy(object.__getattribute__(self, '_proxyconn'), t)
    else:
      return object.__getattribute__(self, '_proxyconn').get(self, attr)
  def __getattr__(self, attr):
    return object.__getattribute__(self, '__getattribute__')(attr)
  def __setattr__(self, attr, val):
    object.__getattribute__(self, '_proxyconn').set(self, attr, val)
  def __delattr__(self, attr):
    object.__getattribute__(self, '_proxyconn').callattr(self, '__delattr__', (attr,), {})
  def __call__(self, *args, **kwargs):
    return object.__getattribute__(self, '_proxyconn').call(self, args, kwargs)
  def __del__(self):
    if not marshal or not struct or not socket: return # Reduce spurious messages when quitting python
    object.__getattribute__(self, '_proxyconn').delete(self)
  def __hash__(self):
    t = object.__getattribute__(self, '_proxyhash')
    if t is None:
      t = object.__getattribute__(self, '_proxyconn').hash(self)
      object.__setattr__(self, '_proxyhash', t)
    return t
  
  # Special methods don't always go through __getattribute__, so redirect them all there.
  for special in ('__repr__', '__str__', '__lt__', '__le__', '__eq__', '__ne__', '__gt__', '__ge__', '__cmp__', '__rcmp__', '__nonzero__', '__unicode__', '__len__', '__getitem__', '__setitem__', '__delitem__', '__iter__', '__reversed__', '__contains__', '__getslice__', '__setslice__', '__delslice__', '__add__', '__sub__', '__mul__', '__floordiv__', '__mod__', '__divmod__', '__pow__', '__lshift__', '__rshift__', '__and__', '__xor__', '__or__', '__div__', '__truediv__', '__radd__', '__rsub__', '__rmul__', '__rdiv__', '__rtruediv__', '__rfloordiv__', '__rmod__', '__rdivmod__', '__rpow__', '__rlshift__', '__rrshift__', '__rand__', '__rxor__', '__ror__', '__iadd__', '__isub__', '__imul__', '__idiv__', '__itruediv__', '__ifloordiv__', '__imod__', '__ipow__', '__ilshift__', '__irshift__', '__iand__', '__ixor__', '__ior__', '__neg__', '__pos__', '__abs__', '__invert__', '__complex__', '__int__', '__long__', '__float__', '__oct__', '__hex__', '__index__', '__coerce__', '__enter__', '__exit__'):
    exec "def {special}(self, *args, **kwargs):\n\treturn object.__getattribute__(self, '_proxyconn').callattr(self, '{special}', args, kwargs)".format(special=special) in None, None

class ProxyInfo(object):
  @classmethod
  def isPacked(self, obj):
    return type(obj) == tuple and len(obj) == 6 and obj[:2] == (StopIteration, Ellipsis)
  @classmethod
  def fromPacked(self, obj):
    return self(obj[2], obj[3], obj[4], obj[5])
  shared_lazyattrs = {}

  def __init__(self, endpoint, remoteid, attrpath = '', lazyattrs = '', dbgnote = ''):
    self.endpoint = endpoint
    self.remoteid = remoteid
    self.attrpath = attrpath
    self.lazyattrs = lazyattrs
    self.dbgnote = dbgnote

  def __repr__(self):
    return 'ProxyInfo'+repr((self.endpoint, self.remoteid)) + ('' if not self.dbgnote else ' <'+self.dbgnote+'>')

  def packed(self):
    return (StopIteration, Ellipsis, self.endpoint, self.remoteid, self.attrpath, self.lazyattrs)

  def getattr(self, attr):
    if not self.lazyattrs: return None
    path = self.attrpath+'.'+attr if self.attrpath else attr
    lz = self.lazyattrs
    if type(lz) == str:
      lz = type(self).shared_lazyattrs[lz]
    if path not in lz: return None
    return type(self)(self.endpoint, self.remoteid, attrpath = path, lazyattrs = self.lazyattrs)

class Connection(object):
  def __init__(self, sock, secret, endpoint = urandom(8).encode('hex')):
    self.sock = sock
    self.secret = secret
    self.endpoint = endpoint
    self.garbage = []

  def runServer(self, obj):
    if self.sock.recv(2) != 'yo': return
    self.sock.sendall(sha1(self.secret+self.sock.recv(20)).digest())
    chal = urandom(20)
    self.sock.sendall(chal)
    if self.sock.recv(20) != sha1(self.secret+chal).digest(): return
    try:
      self.vended = {}
      self.sendmsg(self.pack(obj))
      while self.vended:
        self.handle(self.recvmsg())
    except socket.error as e:
      if e.errno in (errno.EPIPE, errno.ECONNRESET): pass # Client disconnect is a non-error.
      else: raise
    finally:
      del self.vended

  def connectProxy(self):
    self.vended = {}
    self.sock.sendall('yo')
    chal = urandom(20)
    self.sock.sendall(chal)
    if self.sock.recv(20) != sha1(self.secret+chal).digest(): return
    self.sock.sendall(sha1(self.secret+self.sock.recv(20)).digest())
    return self.unpack(self.recvmsg())

  def handle(self, msg):
    if DEBUG: print >> sys.stderr, self.endpoint, self.unpack(msg, True)
    try:
      if msg[0] == 'get':
        _, obj, attr = msg
        reply = ('ok', self.pack(getattr(self.unpack(obj), attr)))
      elif msg[0] == 'set':
        _, obj, attr, val = msg
        setattr(self.unpack(obj), attr, self.unpack(val))
        reply = ('ok', None)
      elif msg[0] == 'call':
        _, obj, args, kwargs = msg
        reply =  ('ok', self.pack(self.unpack(obj)(*self.unpack(args), **self.unpack(kwargs))))
      elif msg[0] == 'callattr':
        _, obj, attr, args, kwargs = msg
        reply =  ('ok', self.pack(getattr(self.unpack(obj), attr)(*self.unpack(args), **self.unpack(kwargs))))
      elif msg[0] == 'gc':
        _, objs = msg
        for obj in objs:
          try:
            k = id(self.unpack(obj))
            self.vended[k][1] -= 1
            if self.vended[k][1] == 0:
              del self.vended[k]
          except:
            print >> sys.stderr, "Exception while releasing", obj
            traceback.print_exc(sys.stderr)
        reply = ('ok', None)
      elif msg[0] == 'hash':
        _, obj = msg
        reply = ('ok', self.pack(hash(self.unpack(obj))))
      else:
        assert False, "Bad message " + repr(x) # Note that this gets caught
    except:
      typ, val, tb = sys.exc_info()
      reply = ('exn', typ.__name__, self.pack(val.args), traceback.format_exception(typ, val, tb))
    
    self.sendmsg(reply)

  def get(self, proxy, attr):
    return self.request(('get', object.__getattribute__(proxy, '_proxyinfo').packed(), attr))
  def set(self, proxy, attr, val):
    self.request(('set', object.__getattribute__(proxy, '_proxyinfo').packed(), attr, self.pack(val)))
  def call(self, proxy, args, kwargs):
    return self.request(('call', object.__getattribute__(proxy, '_proxyinfo').packed(), self.pack(args), self.pack(kwargs)))
  def callattr(self, proxy, attr, args, kwargs):
    return self.request(('callattr', object.__getattribute__(proxy, '_proxyinfo').packed(), attr, self.pack(args), self.pack(kwargs)))
  def hash(self, proxy):
    return self.request(('hash', object.__getattribute__(proxy, '_proxyinfo').packed()))

  def request(self, msg):
    self.sendmsg(msg)
    while True:
      x = self.recvmsg()
      if DEBUG: print >> sys.stderr, self.endpoint, self.unpack(x, True)
      if x[0] == 'ok':
        return self.unpack(x[1])
      elif x[0] == 'exn':
        exntyp = exceptions.__dict__.get(x[1])
        args = self.unpack(x[2])
        trace = x[3]
        if exntyp and issubclass(exntyp, BaseException):
          if DEBUG: print >> sys.stderr, 'Remote '+''.join(trace)
          raise exntyp(*args)
        else:
          raise Exception(str(x[1])+repr(args)+'\nRemote '+''.join(trace))
      else:
        self.handle(x)

  # Note: must send after non-info_only packing, or objects will be left with +1 retain count in self.vended
  def pack(self, val, info_only = False):
    if type(val) in (bool, int, long, float, complex, str, unicode) or val is None or val is StopIteration or val is Ellipsis:
      return val
    elif type(val) == tuple:
      return tuple(self.pack(i, info_only) for i in val)
    elif type(val) == list:
      return [self.pack(i, info_only) for i in val]
    elif type(val) == set:
      return {self.pack(i, info_only) for i in val}
    elif type(val) == frozenset:
      return frozenset(self.pack(i, info_only) for i in val)
    elif type(val) == dict:
      return {self.pack(k, info_only):self.pack(v, info_only) for k,v in val.iteritems()}
    elif type(val) == Proxy:
      return object.__getattribute__(val, '_proxyinfo').packed()
    #elif type(val) == CodeType:
    # Just send code self.vended via proxy
    else:
      if not info_only:
        self.vended.setdefault(id(val), [val, 0])[1] += 1
      return ProxyInfo(self.endpoint, id(val)).packed()

  def unpack(self, val, info_only = False):
    if ProxyInfo.isPacked(val):
      info = ProxyInfo.fromPacked(val)
      try:
        if self.endpoint == info.endpoint:
          try:
            obj = self.vended[info.remoteid][0]
          except KeyError:
            if not info_only:
              raise Exception("Whoops, "+self.endpoint+" can't find reference to object "+repr(info.remoteid))
            else:
              info.dbgnote = 'missing local reference'
              return info
          if info.attrpath:
            for i in info.attrpath.split('.'):
              obj = getattr(obj, i)
          return obj
        else:
          return Proxy(self, info) if not info_only else info
      except:
        if not info_only: raise
        info.dbgnote = 'While unpacking, ' + ''.join(traceback.format_exc())
        return info
    elif type(val) == tuple:
      return tuple(self.unpack(i, info_only) for i in val)
    elif type(val) == list:
      return [self.unpack(i, info_only) for i in val]
    elif type(val) == set:
      return {self.unpack(i, info_only) for i in val}
    elif type(val) == frozenset:
      return frozenset(self.unpack(i, info_only) for i in val)
    elif type(val) == dict:
      return {self.unpack(k, info_only):self.unpack(v, info_only) for k,v in val.iteritems()}
    elif type(val) == CodeType:
      raise Exception('code types get sent via proxy')
    else:
      return val

  def sendmsg(self, msg):
    x = marshal.dumps(msg).encode('zlib')
    self.sock.sendall(struct.pack('<I', len(x)))
    self.sock.sendall(x)

  def recvmsg(self):
    x = self.sock.recv(4)
    if len(x) == 4:
      y = struct.unpack('<I', x)[0]
      z = self.sock.recv(y)
      if len(z) == y:
        return marshal.loads(z.decode('zlib'))
    raise socket.error(errno.ECONNRESET, 'The socket was closed while receiving a message.')

  def delete(self, proxy):
    self.garbage.append(object.__getattribute__(proxy, '_proxyinfo').packed())
    if len(self.garbage) > 100:
      try: self.request(('gc', tuple(self.garbage)))
      except socket.error: pass # No need for complaints about a dead connection
      self.garbage[:] = []

__all__ = [Connection,]

# For demo purposes.
if __name__ == "__main__":
  from sys import argv
  if len(argv) <= 3:
    print >> sys.stderr, "Usage:", argv[0], "server <address> <port> [<password>]"
    print >> sys.stderr, "       python -i", argv[0], "client <address> <port> [<password>]"
    print >> sys.stderr, "In the client python shell, the server's module is available as 'proxy'"
    print >> sys.stderr, "A good demo is `proxy.__builtins__.__import__('ctypes').memset(0,0,1)`"
    exit(64)
  
  hostport = (argv[2], int(argv[3]))
  password = argv[4] if len(argv) > 4 else 'lol, python'
  if argv[1] == 'server':
    import SocketServer
    class Server(SocketServer.BaseRequestHandler):
      def handle(self):
        print >> sys.stderr, 'Accepting client', self.client_address
        Connection(self.request, password).runServer(sys.modules[__name__])
        print >> sys.stderr, 'Finished with client', self.client_address
    SocketServer.TCPServer.allow_reuse_address = True
    SocketServer.TCPServer(hostport, Server).serve_forever()
    exit(1)
  elif argv[1] == 'client':
    proxy = Connection(socket.create_connection(hostport), password).connectProxy()
  else:
    exit(64)