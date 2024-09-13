# A simple wireless simulation environment
import paho.mqtt.client as mqtt
from random import seed, randint
from datetime import datetime
import json
import math
import simpy.rt

RADIO_TXDISTANCE = 1.5  # transmissione range of nodes
RADIO_LOSSRATE   = 10 # 10% packet loss rate
RADIO_CHANNEL    = 99  # selected transmission channel

GW = 'Utz'

DEBUG_RADIO  = False #debug messages for the lowlevel radio True or False
DEBUG_SENSOR = False #debug messages for the lowlevel sensors True or False
DEBUG_ADVERT = True  #debug messages for the advertisement
DEBUG_ROUTE  = False #general routing info
DEBUG_INFO   = False #general info messages

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
        def __init__(self, env, media, id, posx, posy):
                self.env = env
                self.media_in = media.get_output_conn()
                self.media_out = media
                self.channel = RADIO_CHANNEL
                self.id = id
                self.posx = posx
                self.posy = posy
                self.sqnr = 0
                self.rank = 0
                env.process(self.main_p())
                env.process(self.receive_p())

        def temperature(self):
                temp = randint(27, 35)
                if (DEBUG_SENSOR):
                        print(self.env.now,':', self.id,'sensing temperature of', temp)
                return temp

        def send(self, ldst, msg_str):
                if (DEBUG_RADIO):
                        print(self.env.now,':', self.id,'->', ldst)
                msg = (self, self.channel, self.id, ldst, str(msg_str))
                self.media_out.put(msg)

        def receive(self, msg):
                distance =  math.sqrt(((msg[0].posx - self.posx) ** 2) + ((msg[0].posy - self.posy) ** 2))
                if (msg[1] != self.channel) :
                        if (DEBUG_RADIO):
                                print(self.env.now,':', self.id,'X (chan)', msg[2], 'distance', distance)
                        return None
                elif (msg[2] == self.id) :
                        if (DEBUG_RADIO):
                                print(self.env.now,':', self.id,'X (self)', msg[2], 'distance', distance)
                        return None
                elif (distance > RADIO_TXDISTANCE) :
                        if (DEBUG_RADIO):
                                print(self.env.now,':', self.id,'X (range)', msg[2], 'distance', distance)
                        return None
                elif (randint(0,100) < RADIO_LOSSRATE) :
                        if (DEBUG_RADIO):
                                print(self.env.now,':', self.id,'X (loss)', msg[2], 'distance', distance)
                        return None
                else:
                        if ((msg[3] == 0) or (msg[3] == self.id)) :
                                if (DEBUG_RADIO):
                                        print(self.env.now,':', self.id,'<-', msg[2], 'distance', distance)
                                return(str(msg[4]))
                        if (DEBUG_RADIO):
                                print(self.env.now,':', self.id,'X (dst)', msg[2], 'distance', distance)
                        return None


# A sink node
class Sink(Node):
        def on_message(self, client, userdata, msg):
                print("<-: "+msg.topic+" "+str(msg.payload))
                

        def on_connect(self, client, userdata, flags, rc):
                print("connected to MQTT: "+str(rc))

                client.publish("CS4628/" + GW + "/maintenance", "gateway start")
                client.subscribe("CS4628/" + GW + "/command")

        def __init__(self, env, media, id, posx, posy):
                super().__init__(env, media, id, posx, posy)
                self.switch = False;
                self.channel = RADIO_CHANNEL
                self.rank = 1
                print(self.env.now,':', self.id,'new sink node (', self.posx,'|', self.posy,')')
                self.mqttc = mqtt.Client(client_id="", clean_session=True, userdata=None, transport="tcp")
                self.mqttc.on_connect = self.on_connect
                self.mqttc.on_message = self.on_message
                self.mqttc.connect('broker.hivemq.com', 1883, 60)
                self.mqttc.loop_start()

        def publish(self, client, message, node_id, type):
          if type == 'TEMP':
              client.publish("CS4628/" + GW + "/"+ str(node_id) + "/temp" ,message)

        def main_p(self):
                while True:
                        yield self.env.timeout(100)
                        # # send a broadcast advert message
                        self.sqnr += 1
                        msg_json = {}
                        msg_json['TYPE'] = 'JOIN'
                        msg_json['SRC']  = self.id
                        msg_json['DST']  = 0
                        msg_json['LSRC'] = self.id
                        msg_json['LDST'] = 0
                        msg_json['RNK'] = self.rank
                        msg_json['SEQ']  = self.sqnr
                        msg_str = json.dumps( msg_json )
                        if (DEBUG_ADVERT):
                                print(self.env.now,':', self.id ,'sending advert' , msg_str)
                        self.send(msg_json['LDST'],msg_str)


        def receive_p(self):
                while True:
                        msg = yield self.media_in.get()
                        msg_str = self.receive(msg)
                        if msg_str:
                                if (DEBUG_INFO):
                                        print(self.env.now,':', self.id ,'sink, receiving' , msg_str)
                                msg_json = json.loads(msg_str)
                                if msg_json['TYPE'] == 'TEMP':
                                        print(self.env.now,':', self.id ,'sensor',msg_json['SRC'],'reports', msg_json['DATA'])
                                        self.publish(self.mqttc, msg_json['DATA'], msg_json['SRC'], msg_json['TYPE'])



# A sensor node
class Sensor(Node):

        def __init__(self, env, media, id, posx, posy):
                super().__init__(env, media, id, posx, posy)
                self.join_node = 0
                print(self.env.now,':', self.id,'new sensor node (', self.posx,'|', self.posy,')')

        def main_p(self):
                while True:
                        yield self.env.timeout(randint(300, 500))
                        if self.join_node == 0:
                                print(self.env.now,':', self.id ,'cannot send messages, not joined a topology yet')
                        else:
                                # send a temperature message to the sink
                                self.sqnr += 1
                                msg_json = {}
                                msg_json['TYPE'] = 'TEMP'
                                msg_json['SRC']  = self.id
                                msg_json['DST']  = 1
                                msg_json['LSRC'] = self.id
                                msg_json['LDST'] = self.join_node
                                msg_json['SEQ']  = self.sqnr
                                msg_json['DATA'] = self.temperature()
                                msg_str = json.dumps( msg_json )
                                if (DEBUG_INFO):
                                        print(self.env.now,':', self.id ,'sending sensor reading' , msg_str)
                                self.send(msg_json['LDST'],msg_str)

                                # send a join message to all around me
                                self.sqnr += 1
                                msg_json = {}
                                msg_json['TYPE'] = 'JOIN'
                                msg_json['SRC']  = self.id
                                msg_json['DST']  = 0
                                msg_json['LSRC'] = self.id
                                msg_json['LDST'] = 0
                                msg_json['RNK'] = self.rank
                                msg_json['SEQ']  = self.sqnr
                                msg_str = json.dumps( msg_json )
                                if (DEBUG_ADVERT):
                                        print(self.env.now,':', self.id ,'sending advert' , msg_str)
                                self.send(msg_json['LDST'],msg_str)



        def receive_p(self):
                while True:
                        msg = yield self.media_in.get()
                        msg_str = self.receive(msg)
                        if msg_str:
                                if (DEBUG_INFO):
                                        print(self.env.now,':', self.id ,'receiving' , msg_str)
                                msg_json = json.loads(msg_str)
                                if msg_json['TYPE'] == 'JOIN':
                                        if self.join_node == 0 :
                                                if (DEBUG_ADVERT):
                                                        print(self.env.now,':', self.id ,'joining node' , msg_json['SRC'], 'rank:', self.rank, '->', msg_json['RNK'] + 1)
                                                self.join_node = msg_json['SRC']
                                                self.rank = msg_json['RNK'] + 1
                                        else:
                                                if (DEBUG_ADVERT):
                                                        print(self.env.now,':', self.id ,'join received for rank' , msg_json['RNK'] )
                                                if (msg_json['RNK'] + 1 < self.rank):
                                                        if (DEBUG_ADVERT):
                                                                print(self.env.now,':', self.id ,'joining node' , msg_json['SRC'], 'rank:', self.rank, '->', msg_json['RNK'] + 1)
                                                        self.join_node = msg_json['SRC']
                                                        self.rank = msg_json['RNK'] + 1
                                elif msg_json['TYPE'] == 'TEMP':
                                        if self.join_node == 0:
                                                print(self.env.now,':', self.id ,'cannot route messages, not joined a topology yet')
                                        else:
                                                msg_json['LSRC'] = self.id
                                                msg_json['LDST'] = self.join_node
                                                msg_json['DATA'] = str(msg_json['DATA'])
                                                msg_str = json.dumps( msg_json )
                                                if (DEBUG_ROUTE):
                                                        print(self.env.now,':', self.id ,'routing' , msg_str)
                                                self.send(msg_json['LDST'],msg_str)



# Start of main program
# Initialisation of the random generator
seed(datetime.now())

# Setup of the simulation environment
# factor=0.01 means that one simulation time unit is equal to 0.01 seconds
#env = simpy.Environment()
env = simpy.rt.RealtimeEnvironment(factor=0.01, strict=False)

# the communication medium
media = Media(env)

# Nodes placed in a 2 dimensional space
# Node(env, media, node_id, position_x, position_y)
Sink(env,media,1,1,0)
Sensor(env,media,2,0,1)
Sensor(env,media,3,0,2)
Sensor(env,media,4,0,3)
Sensor(env,media,5,2,1)
Sensor(env,media,6,2,2)
Sensor(env,media,7,2,3)

# Duration of the experiment
# env.run(until=6000)
env.run()
