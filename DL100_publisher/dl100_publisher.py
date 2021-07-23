import argparse
import datetime
import os
import random
import struct
import sys
import threading
import time

from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import zmq

import cpppo
from cpppo.server.enip import client, poll
from cpppo.server.enip.get_attribute import attribute_operations, proxy_simple as device

import logging
cpppo.log_cfg['level'] = logging.ERROR


def make_msg(ts, v1, v2):
    msg = f"{datetime.datetime.fromtimestamp(ts/1e3).isoformat()} - {ts}, {v1:8.0f}, {v2:12.2f}"
    msg = msg + " " * (80 - len(msg))
    return msg


def pack_bytes(ts: int, v1: int, v2: int, verbose: bool = False):
    if verbose:
        msg = make_msg(ts=ts, v1=v1, v2=v2)
        sys.stdout.write("\r" + msg)

    return struct.pack("<Qii", int(ts), int(v1), int(v2))


class Publisher:
    """
    The Publisher class connects via cpppo to an Sick DL100 distance sensor and publishes it's distance + velocity measurements via zmq.
    """

    def __init__(
        self,
        bind_str: str,
        host: str,
        port: int = 44818,
        verbose: bool = True,
        context: zmq.Context = zmq.Context(),
    ):
        """Init method

        params
        ------
        bind_str : str   Connection string for zmq socket which  messages made by pack_bytes() will be sent to.  E.g. inproc://dl100 or tcp://localhost:8090
        host:   str Hostname of DL100 device
        port:   str Port for DL100 Ethernet/IP  communication
        verbose:    Bool    Print the current values
        context:    zmq.Context     Context object to use. When using inproc, need to pass context which was also used for receiver socket
        """

        self.host = host
        self.port = port  # 44818: port for Ethernet IP
        self.verbose = verbose

        self.zmq_active = False
        self.pub_socket = None

        self.poller: Optional[threading.Thread] = None

        self.setup_zmq(bind_str, context)

        self.keymap: Dict[Tuple[str, str], int] = {
            ("@0x23/1/10", "DINT"): 1,  # distance
            ("@0x23/1/24", "DINT"): 2,  # velocity
        }

        self.values = {}

    def toggle_zmq_active(self):
        if self.zmq_active:
            self.zmq_active = False
        else:
            self.zmq_active = True
        return self.zmq_active

    def callback_send_zmq(self, par: Tuple[str, str], val: List[float]):
        """
        Forward messages once both measurements (distance + velocity) have arrived.
        message format: timestamp (of distance measurement), distance_vaue, velocity_value
        """
        ts = int(time.time() * 1e3)

        if par == ("@0x23/1/10", "DINT"):
            name = "distance"
        elif par == ("@0x23/1/24", "DINT"):
            name = "velocity"
        else:
            raise ValueError(f"Unknown value received: {par}")

        self.values.update({f"ts_{name}": ts, f"{name}": val[0]})

        if self.zmq_active:
            if list(self.values.keys()) == [
                "ts_distance",
                "distance",
                "ts_velocity",
                "velocity",
            ]:
                # value collection complete, now send them out via zmq
                bytes = pack_bytes(
                    ts=self.values["ts_distance"],
                    v1=self.values["distance"],
                    v2=self.values["velocity"],
                    verbose=self.verbose,
                )
                self.pub_socket.send(bytes)

                # reset Dict
                self.values = {}

    def send_random_data(self, cycle: float = 1 / 50, generate_zeros: bool = False):
        prev_dist = 0
        try:
            while True:
                ts = time.time()
                if generate_zeros:
                    dist = 0
                else:
                    dist = 2500 + int((random.random() - 0.5) * 1000)
                vel = (dist - prev_dist) * cycle

                bytes = pack_bytes(
                    ts=int(ts * 1e3), v1=dist, v2=vel, verbose=self.verbose
                )
                self.pub_socket.send(bytes)

                prev_dist = dist
                time.sleep(max(0, cycle - (time.time() - ts)))

        except KeyboardInterrupt:
            pass

    def start_data_polling(self, cycle: float = 1 / 50):
        """
        Setup cpppo polling thread, reading the measurements from an Ethernet Connection to the Distance Scanner.

        Parameters:
        cycle (float): The cycle length for measurement polling
        mode (str):
        """
        callback = self.callback_send_zmq

        self.poller = threading.Thread(
            target=poll.poll,
            kwargs={
                "proxy_class": device,
                "address": (self.host, self.port),
                "cycle": cycle,
                "timeout": 0.5,
                "process": lambda par, val: callback(par=par, val=val),
                "params": list(self.keymap.keys()),
            },
        )
        self.poller.daemon = True
        self.poller.start()

    def setup_zmq(self, bind_str, context):
        if self.pub_socket and not self.pub_socket.closed:
            self.destroy_zmq()

        self.pub_socket = context.socket(zmq.PUB)
        self.pub_socket.setsockopt(zmq.CONFLATE, 1)
        self.pub_socket.bind(bind_str)
        self.zmq_active = True

    def destroy_zmq(self):
        self.zmq_active = False
        self.pub_socket.close()
        print(f"Closing socket")


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dl100-port",
        type=int,
        required=False,
        default=44818,
        help="The port used by the DL100 distance scanner",
    )
    parser.add_argument(
        "--dl100-ip",
        type=str,
        required=False,
        default="192.168.101.217",
        help="The IP of the DL100 distance scanner",
    )
    parser.add_argument(
        "--bind-str",
        type=str,
        required=False,
        default="tcp://localhost:5559",
        help="Address to bind to",
    )

    parser.add_argument(
        "--cycle",
        type=float,
        required=False,
        default=1 / 30,
        help="The cycle length of measurements published via zmq",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        required=False,
        help="Activates verbose output",
    )

    parser.add_argument(
        "--send-bullshit",
        action="store_true",
        required=False,
        help="Send random sample data",
    )

    parser.add_argument(
        "--send-zeros",
        action="store_true",
        required=False,
        help="Send distance==0 data (i.e. invalid/reflector plate missed)",
    )

    args = parser.parse_args()
    print(args)

    pub = Publisher(
        bind_str=arg.bind_str,
        host=args.dl100_ip,
        port=args.dl100_port,
        verbose=args.verbose,
    )
    if args.send_bullshit:
        pub.send_random_data(cycle=args.cycle, generate_zeros=args.send_zeros)
    else:
        pub.start_data_polling(cycle=args.cycle)

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
