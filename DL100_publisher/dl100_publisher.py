import argparse
import datetime
import os
import random
import struct
import sys
import threading
import time

from typing import Dict, List, Optional, Tuple, Union

import zmq
from zmq.auth.thread import ThreadAuthenticator

import cpppo
from cpppo.server.enip import client, poll
from cpppo.server.enip.get_attribute import attribute_operations, proxy_simple as device


def str2bool(v: Union[bool, str]):
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError("Boolean value expected.")


def make_msg(ts, v1, v2):
        msg = f"{datetime.datetime.fromtimestamp(ts/1e3).isoformat()} - {ts}, {v1:8.0f}, {v2:12.2f}"
        msg = msg + " " * (80 - len(msg))
        return msg


def pack_bytes(ts: int, v1: int, v2: int, verbose: bool = False):
    if verbose:
        msg = make_msg(ts=ts, v1=v1, v2=v2)
        sys.stdout.write("\r" + msg)

    return (
        struct.pack("<Q", int(ts))
        + struct.pack("<i", int(v1))
        + struct.pack("<i", int(v2))
    )

class Publisher:
    """
    The Publisher class connects via cpppo to an Sick DL100 distance sensor and publishes it's distance + velocity measurements via zmq.
    """

    def __init__(
        self,
        zmq_port: int,
        host: str,
        port: int = 44818,
        verbose: bool = True,
    ):
        """Init method

        Parameters:
            zmq_port (int): The port used by zmq to publish values
            host (str): The IP of the DL100 distance scanner
            port (int): The port used by the dl100 distance scanner
            verbose (bool): Activate verbose mode
        """

        self.host = host
        self.port = port  # 44818: port for Ethernet IP
        self.zmq_port = zmq_port
        self.verbose = verbose

        self.zmq_active = False
        self.pub_socket = None

        self.poller: Optional[threading.Thread] = None

        self.setup_zmq()

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

    def callback_zmq_single(self, par: Tuple[str, str], val: List[float]):
        """
        Forward dl100 messages directly via zmq.
        message format: timestamp, value_type (1: distance, 2: velocity), value
        """
        ts = int(time.time() * 1e3)
        val_type = self.keymap[par]

        if self.zmq_active:
            bytes = pack_bytes(
                ts=ts,
                v1=val_type,
                v2=val[0],
                verbose=self.verbose
            )
            self.pub_socket.send(bytes)

    def callback_zmq_multi(self, par: Tuple[str, str], val: List[float]):
        """
        Forward messages once both measurements (distance + velocity) have arrived.
        message format: timestamp (of distance measurement), distance_vaue, velocity_value
        """
        ts = int(time.time() * 1e3)

        if par == ("@0x23/1/10", "DINT"):
            name = 'distance'
        elif par == ("@0x23/1/24", "DINT"):
            name = 'velocity'
        else:
            raise ValueError(f"Unknown value received: {par}")

        self.values.update(
            {
                f"ts_{name}": ts,
                f"{name}": val[0]
            }
        )

        if self.zmq_active:
            if list(self.values.keys()) == ['ts_distance', 'distance', 'ts_velocity', 'velocity']:
                # value collection complete, now send them out via zmq
                bytes = pack_bytes(
                    ts=self.values['ts_distance'],
                    v1=self.values['distance'],
                    v2=self.values['velocity'],
                    verbose=self.verbose)
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
                    ts=int(ts*1e3),
                    v1=dist,
                    v2=vel,
                    verbose=self.verbose
                )
                self.pub_socket.send(bytes)

                prev_dist = dist
                time.sleep(max(0, cycle - (time.time()-ts)))

        except KeyboardInterrupt:
            pass

    def start_data_polling(self, cycle: float = 1 / 50, mode: str = 'multi'):
        """
        Setup cpppo polling thread, reading the measurements from an Ethernet Connection to the Distance Scanner.

        Parameters:
            cycle (float): The cycle length for measurement polling
            mode (str):
        """
        if mode == 'single':
            callback = self.callback_zmq_single
        elif mode == 'multi':
            callback = self.callback_zmq_multi

        else:
            raise ValueError(f"Unknown polling_callback mode: {mode}")

        self.poller = threading.Thread(
            target=poll.poll,
            kwargs={
                "proxy_class": device,
                "address": (self.host, self.port),
                "cycle": cycle,
                "timeout": 0.5,
                "process": lambda par, val: callback(
                    par=par, val=val
                ),
                "params": list(self.keymap.keys()),
            },
        )
        self.poller.daemon = True
        self.poller.start()

    def setup_zmq(self):
        if self.pub_socket and not self.pub_socket.closed:
            self.destroy_zmq()

        context = zmq.Context()

        # Username/password from the environment. Note that this does not
        # encrypt communication, just plain text authentication for now.
        AC_USER = os.environ.get("AC_USER", None)
        AC_PASS = os.environ.get("AC_PASS", None)

        # Start authentication thread. All sockets on context will use this
        # handler. Make sure to set the `plain_server` variable on each socket.
        if AC_USER and AC_PASS:
            auth = ThreadAuthenticator(context)
            auth.start()
            auth.allow("127.0.0.1")
            auth.configure_plain(domain="*", passwords={AC_USER: AC_PASS})

        # Create publisher.
        self.pub_socket = context.socket(zmq.PUB)
        self.pub_socket.plain_server = AC_USER and AC_PASS
        print("Publishing zmq msgs on port {port}".format(port=self.zmq_port))
        bind_addr = "tcp://*:{port}".format(port=self.zmq_port)
        self.pub_socket.bind(bind_addr)
        self.zmq_active = True

    def destroy_zmq(self):
        self.zmq_active = False
        self.pub_socket.close()
        print(f"Closing port {self.zmq_port}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dl100_port",
        type=int,
        required=False,
        default=44818,
        help="The port used by the DL100 distance scanner",
    )
    parser.add_argument(
        "--dl100_ip",
        type=str,
        required=False,
        default="192.168.101.217",
        help="The IP of the DL100 distance scanner",
    )
    parser.add_argument(
        "--zmq_port",
        type=int,
        required=False,
        default=5559,
        help="The port used by zmq to publish values",
    )

    parser.add_argument(
        "--cycle",
        type=float,
        required=False,
        default=1 / 30,
        help="The cycle length of measurements published via zmq",
    )

    parser.add_argument(
        "--mode",
        type=str,
        required=False,
        default='multi',
        help="Choose whether to send small zmq-messages per received value, or aggregate distance+velocity into one zmq-message. Options: [single, multi]",
    )

    parser.add_argument(
        "--verbose",
        type=str2bool,
        required=False,
        default=True,
        help="Activates verbose output",
    )

    parser.add_argument(
        "--send-bullshit",
        type=str2bool,
        required=False,
        default=False,
        help="Send random sample data",
    )

    parser.add_argument(
        "--send-zeros",
        type=str2bool,
        required=False,
        default=False,
        help="Send distance==0 data (i.e. invalid/reflector plate missed)",
    )

    args = parser.parse_args()
    print(args)

    pub = Publisher(
        host=args.dl100_ip,
        port=args.dl100_port,
        zmq_port=args.zmq_port,
        verbose=args.verbose,
    )
    if args.send_bullshit:
        pub.send_random_data(cycle=args.cycle, generate_zeros=args.send_zeros)
    else:
        pub.start_data_polling(cycle=args.cycle, mode=args.mode)

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
