# Copyright (c) The University of Edinburgh 2014-2015
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

'''
Dynamic Using Redis.

refer to redis document: https://redis.io/docs/manual/data-types/streams
'''
import argparse
import atexit
import uuid
import redis
import copy
import multiprocessing
import time
import json

from dispel4py.core import GROUPING
from dispel4py.new import processor

# ====================
# Constants
# ====================
# Redis stream prefix
REDIS_STREAM_PREFIX = "DISPEL4PY_DYNAMIC_STREAM_"
# Redis group prefix
REDIS_STREAM_GROUP_PREFIX = "DISPEL4PY_DYNAMIC_GROUP_"

# Redis stream data type must be a dict, this is the key
REDIS_STREAM_DATA_DICT_KEY = b'0'

# Redis message count pre-read
REDIS_READ_COUNT = 1

# Redis read parameter. To enable its blocking read and never timeout
REDIS_BLOCKING_FOREVER = 0
# Read timeout from the global stateless stream
REDIS_STATELESS_STREAM_READ_TIMEOUT = 1000
# Read timeout from the specified stateful stream
REDIS_STATEFUL_STREAM_READ_TIMEOUT = 500
# Stateful process work for stateless time after no stateful data founded
REDIS_STATEFUL_TAKEOVER_PERIOD = 2000

# Redis lock renew interval in ms for stateful process
REDIS_LOCK_RENEW_INTERVAL = 10000

# singal to end of process
SIGNAL_TERMINATED = "TERMINATED"

def parse_args(args, namespace):
    """
        Parse args for dynamic redis
    """
    parser = argparse.ArgumentParser(prog='dispel4py',
                                     description='Submit a dispel4py graph to redis dynamic processing')
    parser.add_argument('-ri', '--redis-ip', required=True, help='IP address of external redis server')
    parser.add_argument('-rp', '--redis-port', help='External redis server port,default 6379', type=int, default=6379)
    parser.add_argument('-n', '--num', metavar='num_processes', required=True, type=int,
                        help='number of processes to run')
    result = parser.parse_args(args, namespace)
    return result


def _get_destination(graph, node, output_name):
    """
        This function is to get the destinations of a certain node in the graph
    """
    result = set()
    pe_id = node.getContainedObject().id

    for edge in graph.edges(node, data=True):

        direction = edge[2]['DIRECTION']
        source = direction[0]
        dest = direction[1]

        if source.id == pe_id and output_name == edge[2]['FROM_CONNECTION']:
            dest_input = edge[2]['TO_CONNECTION']

            if hasattr(dest, "stateful"):
                groupingtype = dest.stateful
                if isinstance(groupingtype, list):
                    # TODO How to do ?
                    # communication = GroupByCommunication(dest_processes, dest_input, groupingtype)
                    pass
                elif groupingtype == 'all':
                    for i in range(dest.numprocesses):
                        result.add((dest.id, dest_input, i))
                elif groupingtype == 'global':
                    result.add((dest.id, dest_input, 0))
            else:
                result.add((dest.id, dest_input, -1))

    return result


class RedisWriter():
    """
        This class is written for PE when using PE.write() function, write data to redis
    """

    def __init__(self, r, redis_stream_name, node, output_name, workflow):
        self.r = r
        self.redis_stream_name = redis_stream_name
        self.node = node
        self.output_name = output_name
        self.workflow = workflow

    def write(self, data):

        # get the destinations of the PE
        destinations = _get_destination(self.workflow.graph, self.node, self.output_name)

        # if the PE has no destinations, then print the data
        if not destinations:
            print('Output collected from %s: %s' % (self.node.getContainedObject().id, data))
        # otherwise, put the data in the destinations to the queue
        else:
            for dest_id, input_name in destinations:
                print('sending to %s with value: %s' % (dest_id, data))
                self.r.xadd(self.redis_stream_name, (dest_id, {input_name: data}))


def _communicate(pes, nodes, value, proc, r, redis_stream_name, workflow):
    """
        This function is to process the data of the queue in the certain PE
    """
    try:
        pe_id, data = value
        # print('%s receive input: %s in process %s' % (pe_id, data, proc))

        pe = pes[pe_id]
        node = nodes[pe_id]

        # TODO should found the right target stream name. Some for stateful, some for stateless.
        for o in pe.outputconnections:
            pe.outputconnections[o]['writer'] = RedisWriter(r, redis_stream_name, node, o, workflow)

        output = pe.process(data)

        if output:
            for output_name, output_value in output.items():
                # get the destinations of the PE
                destinations = _get_destination(workflow.graph, node, output_name)
                # if the PE has no destinations, then print the data
                if not destinations:
                    print('Output collected from %s: %s in process %s' % (pe_id, output_value, proc))
                # otherwise, put the data in the destinations to the queue
                else:
                    for dest_id, input_name, dest_instance in destinations:
                        print('sending to %s with value: %s in processs %s' % (dest_id, output_value, proc))

                        if dest_instance != -1:
                            # stateful
                            r.xadd(f"{redis_stream_name}_{dest_id}_{dest_instance}",
                                   {REDIS_STREAM_DATA_DICT_KEY: json.dumps((dest_id, {input_name: output_value}))})
                        else:
                            r.xadd(redis_stream_name,
                                   {REDIS_STREAM_DATA_DICT_KEY: json.dumps((dest_id, {input_name: output_value}))})

    except Exception as e:
        pass


def _redis_lock(r, stateful_instance_id):
    """
        Redis distributed lock.
    """
    return r.set(stateful_instance_id, "", ex=30, nx=True)


def _redis_lock_renew(r, stateful_instance_id):
    """
        Renew the Redis distributed lock.
    """
    return r.set(stateful_instance_id, "", ex=30)


def _release_redis_lock(r, stateful_instance_id):
    """
        Release Redis distributed lock.
        return True if not terminated
    """
    return r.delete(stateful_instance_id)

def process_stateful(r, redis_stream_name, redis_stream_group_name,stateful_instance_id, proc, pes, nodes, workflow):
    """
        Read and process stateful data from redis
        return True if not terminated
    """
    # Try to read from stateful stream first
    response = r.xreadgroup(redis_stream_group_name, f"consumer:{proc}",
                            {f"{redis_stream_name}_{stateful_instance_id}": ">"}, REDIS_READ_COUNT,
                            REDIS_STATEFUL_STREAM_READ_TIMEOUT, True)
    if not response:
        # read timeout, because no data, read stateless data instead
        print(
            f"stateful process:{proc} for instance:{stateful_instance_id} get no data in {REDIS_STATEFUL_STREAM_READ_TIMEOUT}ms, take stateless now")

        # read stateless data instead
        begin = time.time()
        while time.time() - begin < REDIS_STATEFUL_TAKEOVER_PERIOD:
            if not process_stateless(r, redis_stream_name, redis_stream_group_name, proc, pes, nodes, workflow):
                return False
    else:
        redis_id, value = _decode_redis_stream_data(response)
        _communicate(pes, nodes, value, proc, r, redis_stream_name, workflow)

    return True

def process_stateless(r, redis_stream_name, redis_stream_group_name, proc, pes, nodes, workflow):
    """
        Read and process stateless data from redis
    """
    response = r.xreadgroup(redis_stream_group_name, f"consumer:{proc}", {redis_stream_name: ">"}, REDIS_READ_COUNT,
                            REDIS_STATELESS_STREAM_READ_TIMEOUT, True)

    if not response:
        # read timeout, because no data, continue to read
        print(f"process:{proc} get no data in {REDIS_STATELESS_STREAM_READ_TIMEOUT}ms.")
    else:
        redis_id, value = _decode_redis_stream_data(response)
        if value == SIGNAL_TERMINATED:
            # push another SIGNAL_TERMINATED into the global stateless queue
            r.xadd(redis_stream_name, {REDIS_STREAM_DATA_DICT_KEY: json.dumps(SIGNAL_TERMINATED)})
            return False
        _communicate(pes, nodes, value, proc, r, redis_stream_name, workflow)

    return True


def _process_worker(workflow, redis_ip, redis_port, redis_stream_name, redis_stream_group_name, proc, stateful=False,
                    stateful_instance_id=None):
    """
        This function is to process the workflow in a certain process
    """
    pes = {node.getContainedObject().id: node.getContainedObject() for node in workflow.graph.nodes()}
    nodes = {node.getContainedObject().id: node for node in workflow.graph.nodes()}

    # connect to redis
    r = redis.Redis(redis_ip, redis_port)

    # Lock if process stateful
    if stateful:
        if not _redis_lock(r, stateful_instance_id):
            return f"Cannot acquire distributed lock for {stateful_instance_id}."

    last_renew_time = time.time()

    while True:
        if stateful:
            if not process_stateful(r, redis_stream_name, redis_stream_group_name,stateful_instance_id, proc, pes, nodes, workflow):
                _release_redis_lock(r, stateful_instance_id)
                print(f"TERMINATED: stateful process:{proc} for instance:{stateful_instance_id} ends now")
                break

            # Renew lock periodically
            # still a weak guarantee, will be bad if process data takes too long, but may be fine for most case
            if time.time() > last_renew_time + REDIS_LOCK_RENEW_INTERVAL:
                if not _redis_lock_renew(r, stateful_instance_id):
                    return f"Renew distributed lock for{stateful_instance_id} encounter a problem."
                last_renew_time = time.time()
        else:
            if not process_stateless(r, redis_stream_name, redis_stream_group_name, proc, pes, nodes, workflow):
                print(f"TERMINATED: stateless process:{proc} ends now")
                break


def _decode_redis_stream_data(redis_response):
    """
        Decode the data of redis stream, return the redis id and value
    """
    key, message = redis_response[0]
    redis_id, data = message[0]
    value = json.loads(data.get(REDIS_STREAM_DATA_DICT_KEY))
    return redis_id, value


def clean_redis_on_exit(redis_connection, default_redis_stream_name):
    """
        Clean redis stream when exit
    """
    print("Begin to clean redis stream keys...")
    scanresult = redis_connection.scan(0, f"{default_redis_stream_name}*", 1000)
    if scanresult:
        next_cursor, redis_keys = scanresult
        for key in redis_keys:
            redis_connection.delete(key)


def process(workflow, inputs, args):
    """
        This function is to process the workflow with given inputs and args
    """
    elapsed_time = 0
    start_time = time.time()
    jobid = str(uuid.uuid1())

    # create redis stream and group
    # Redis stream name & group name
    default_redis_stream_name = REDIS_STREAM_PREFIX + jobid
    redis_stream_group_name = REDIS_STREAM_GROUP_PREFIX + jobid

    # connect to redis
    redis_connection = redis.Redis(args.redis_ip, args.redis_port)

    # redis stream delete existing
    if redis_connection.exists(default_redis_stream_name):
        redis_connection.delete(default_redis_stream_name)

    # create consumer group, read FIFO, auto create stream
    redis_connection.xgroup_create(default_redis_stream_name, redis_stream_group_name, "$", True)

    # register exit hook to clean redis stream
    atexit.register(clean_redis_on_exit, redis_connection, default_redis_stream_name)

    # process size
    size = args.num

    has_provided_input = False
    stateful_nodes = []
    for node in workflow.graph.nodes():
        # find stateful nodes
        pe = node.getContainedObject()

        for inputconnection in pe.inputconnections.values():
            if inputconnection.get(GROUPING):
                pe.stateful = inputconnection[GROUPING]
                stateful_nodes.append(node)

        # handle provided input(here assuming provided inputs is not given to stateful node)
        provided_inputs = processor.get_inputs(pe, inputs)
        if provided_inputs is not None:
            if hasattr(pe, "stateful"):
                raise "Provided inputs is not supported by stateful node"

            has_provided_input = True
            if isinstance(provided_inputs, int):
                for i in range(provided_inputs):
                    redis_connection.xadd(default_redis_stream_name,
                                          {REDIS_STREAM_DATA_DICT_KEY: json.dumps((pe.id, {}))})
            else:
                for d in provided_inputs:
                    redis_connection.xadd(default_redis_stream_name,
                                          {REDIS_STREAM_DATA_DICT_KEY: json.dumps((pe.id, d))})

    # end of input
    if has_provided_input:
        redis_connection.xadd(default_redis_stream_name, {REDIS_STREAM_DATA_DICT_KEY: json.dumps(SIGNAL_TERMINATED)})

    # check if process number >=  minimal require of stateful pes
    minimal_stateful_process = sum(map(lambda x: x.getContainedObject().numprocesses, stateful_nodes))
    if size < minimal_stateful_process:
        raise "Process number less than minial requirement of graph"



    # init workers
    prepare_workers = {}
    for proc in range(size):
        cp = copy.deepcopy(workflow)
        cp.rank = proc
        prepare_workers[proc] = cp

    # init jobs
    jobs = []

    # stateful jobs
    for node in stateful_nodes:
        pe = node.getContainedObject()
        # create redis stream for each instance
        for i in range(pe.numprocesses):
            instance_id = f"{pe.id}_{i}"
            redis_connection.xgroup_create(f"{default_redis_stream_name}_{instance_id}", redis_stream_group_name, "$",
                                           True)
            # randomly choose one
            proc, workflow = prepare_workers.popitem()
            p = multiprocessing.Process(target=_process_worker, args=(
                workflow, args.redis_ip, args.redis_port, default_redis_stream_name, redis_stream_group_name, proc,
                True, instance_id))
            jobs.append(p)

    for proc, workflow in prepare_workers.items():
        # stateless jobs
        p = multiprocessing.Process(target=_process_worker, args=(
            workflow, args.redis_ip, args.redis_port, default_redis_stream_name, redis_stream_group_name, proc))
        jobs.append(p)

    # TODO Monitor?

    print('Starting %s workers communicating' % (len(jobs)))
    for j in jobs:
        j.start()
    for j in jobs:
        j.join()

    print("ELAPSED TIME: " + str(time.time() - start_time))