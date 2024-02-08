# A simple wireless simulation environment
from random import seed, randint
from datetime import datetime
import json
import math
import simpy.rt

RADIO_MIN_POWER = 2  # minimum receiving power of nodes
RADIO_LOSSRATE   = 10 # 10% packet loss rate
RADIO_CHANNEL	 = 7  # selected transmission channel

DEBUG_RADIO  = True #debug messages for the lowlevel radio True or False
DEBUG_SENSOR = True #debug messages for the lowlevel sensors True or False

# The media, the wireless channel to communicate
class Media(object):
	def __init__(self, env, capacity=simpy.core.Infinity):
		self.env = env
		self.capacity = capacity
		self.pipes = []

	def put(self, value):
		if not self.pipes:
				raise RuntimeError('There are no output pipes.')
		events = [store.put(value) for store in self.pipes]
		return self.env.all_of(events) 

	def get_output_conn(self):
		pipe = simpy.Store(self.env, capacity=self.capacity)
		self.pipes.append(pipe)
		return pipe

# A node, providing basic sensing and communication API
class Node(object):
	def __init__(self, env, media, id, posx, posy, transmission_power):
		self.env = env
		self.media_in = media.get_output_conn()
		self.media_out = media
		self.channel = RADIO_CHANNEL
		self.id = id
		self.posx = posx
		self.posy = posy
		self.transmission_power = transmission_power
		self.sqnr = 0
		self.dst = 0
		self.ldst = 0
		env.process(self.main_p())
		env.process(self.receive_p())

	def temperature(self):
		temp = randint(27, 35)
		if (DEBUG_SENSOR):
                	print(self.env.now,':', self.id,' sensing temperature of ', temp)
		return temp 

	def send(self, ldst, msg_str):
		if (DEBUG_RADIO):
			print(self.env.now,':', self.id,' -> ', ldst)
		msg = (self, self.channel, self.id, ldst, str(msg_str))
		self.media_out.put(msg)

	def receive(self, msg):
		distance =  math.sqrt(((msg[0].posx - self.posx) ** 2) + ((msg[0].posy - self.posy) ** 2))
		if distance == 0:
			received_power = msg[0].transmission_power
		else:
			received_power = msg[0].transmission_power/(distance ** 2)

		if (msg[1] != self.channel) :
			if (DEBUG_RADIO):
				print(self.env.now,':', self.id,' X  (chan) ', msg[2], ' distance ', distance)
			return None
		elif (msg[2] == self.id) :
			if (DEBUG_RADIO):
				print(self.env.now,':', self.id,' X  (self) ', msg[2], ' distance ', distance)
			return None
		elif (received_power < RADIO_MIN_POWER) :
			if (DEBUG_RADIO):
				print(self.env.now,':', self.id,' X  (range)', msg[2], ' distance ', distance)
			return None
		elif (randint(0,100) < RADIO_LOSSRATE) :
			if (DEBUG_RADIO):
				print(self.env.now,':', self.id,' X  (loss)', msg[2], ' distance ', distance)
			return None
		else:
			if ((msg[3] == 0) or (msg[3] == self.id)) :
				if (DEBUG_RADIO):
					print(self.env.now,':', self.id,' <- ', msg[2], ' distance ', distance)
				return(str(msg[4]))
			if (DEBUG_RADIO):
				print(self.env.now,':', self.id,' X  (dst)', msg[2], ' distance ', distance)
			return None


# A sink node
class Sink(Node):
	def __init__(self, env, media, id, posx, posy, transmission_power):
		super().__init__(env, media, id, posx, posy, transmission_power)
		print(self.env.now,':', self.id,' new sink node (', self.posx,'|', self.posy,')')

	def main_p(self):
		# JOIN MESSAGE
		channel = randint(1, 6)
		self.sqnr += 1
		msg_json = {}
		msg_json['TYPE'] = "JOIN" 
		msg_json['SRC']  = self.id 
		msg_json['DST']  = 0 
		msg_json['LSRC'] = self.id 
		msg_json['LDST'] = 0 
		msg_json['SEQ']  = self.sqnr
		msg_json['DATA'] = channel
		msg_str = json.dumps( msg_json ) 
		print(self.env.now,':', self.id ,' sending ' , msg_str)
		self.send(msg_json['LDST'],msg_str)
		self.channel = channel

		while True:
			yield self.env.timeout(100)	
			print(self.env.now,':', self.id ,' sink, waiting for messages')


	def receive_p(self):
		while True:
			msg = yield self.media_in.get()
			msg_str = self.receive(msg)
			if msg_str: 
				print(self.env.now,':', self.id ,' sink, receiving ' , msg_str)

# A sensor node
class Sensor(Node):
	def __init__(self, env, media, id, posx, posy, transmission_power):
		super().__init__(env, media, id, posx, posy, transmission_power)
		print(self.env.now,':', self.id,' new sensor node (', self.posx,'|', self.posy,')')
		self.ready = False

	def main_p(self):
		while True:
			yield self.env.timeout(randint(500, 1000))
			if self.ready:	
				self.sqnr += 1
				# the message here is sent as broadcast for address 0
				msg_json = {}
				msg_json['TYPE'] = "TEMP" 
				msg_json['SRC']  = self.id 
				msg_json['DST']  = self.dst
				msg_json['LSRC'] = self.id 
				msg_json['LDST'] = self.ldst 
				msg_json['SEQ']  = self.sqnr
				msg_json['DATA'] = self.temperature() 
				msg_str = json.dumps( msg_json ) 
				print(self.env.now,':', self.id ,' sending ' , msg_str)
				self.send(msg_json['LDST'],msg_str)

	def receive_p(self):
		while True:
			msg = yield self.media_in.get()
			msg_str = self.receive(msg)
			if not self.ready:
				if msg_str:
					msg_json = json.loads(msg_str)
					try:
						if msg_json['TYPE'] == "JOIN":
							self.channel = msg_json['DATA']
							self.dst = msg_json['SRC']
							self.ldst = msg_json['LSRC']
							print(self.env.now, ':', self.id, ' received JOIN message. Channel:', self.channel, ' DST:', self.dst, ' LDST:', self.ldst)
							self.ready = True
					except (json.JSONDecodeError, KeyError):
						# Ignore invalid or incomplete JSON messages
						pass
			else:
				if msg_str: 
					print(self.env.now,':', self.id ,' receiving ' , msg_str)

# Start of main program
# Initialisation of the random generator
seed(datetime.now())

# Setup of the simulation environment
# factor=0.01 means that one simulation time unit is equal to 0.01 seconds
#env = simpy.Environment()
env = simpy.rt.RealtimeEnvironment(factor=0.01)

# the communication medium 
media = Media(env)

# Nodes placed in a 2 dimensional space
# Node(env, media, node_id, position_x, position_y)
Sink(env,media,1,1,0,8)
Sensor(env,media,2,0,1,8)
Sensor(env,media,3,0,2,8)
Sensor(env,media,4,2,1,8)
Sensor(env,media,5,2,2,8)
Sink(env,media,6,1,3,8)

# Duration of the experiment
env.run(until=6000)
