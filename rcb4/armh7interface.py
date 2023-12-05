import struct

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection
import numpy as np
import serial

from rcb4.asm import four_bit_to_num
from rcb4.asm import rcb4_checksum
from rcb4.asm import rcb4_servo_ids_to_5bytes
from rcb4.asm import rcb4_servo_positions
from rcb4.asm import rcb4_servo_svector
from rcb4.asm import rcb4_velocity
from rcb4.ctype_utils import c_type_to_size
from rcb4.data import kondoh7_elf
from rcb4.rcb4interface import CommandTypes
from rcb4.rcb4interface import rcb4_dof
from rcb4.rcb4interface import ServoParams
from rcb4.struct_header import c_vector
from rcb4.struct_header import DataAddress
from rcb4.struct_header import Madgwick
from rcb4.struct_header import max_sensor_num
from rcb4.struct_header import sensor_sidx
from rcb4.struct_header import SensorbaseStruct
from rcb4.struct_header import ServoStruct
from rcb4.struct_header import WormmoduleStruct


armh7_variable_list = [
    "walking_command",
    "walking_mode",
    "rom_to_flash",
    "flash_to_rom",
    'Mfilter',
    "set_sidata_command",
    "set_sdata_command",
    "set_edata_command",
    "sidata_to_dataram",
    "dataflash_to_dataram",
    'servo_vector',
    "dataram_to_dataflash",
    "_sidata",
    "_sdata",
    "uwTickPrio",
    "__fdlib_version",
    "_impure_ptr",
    "_edata",
    "_sbss",
    "_ebss",
    "servo_idmode_scan",
    "buzzer_init_sound",
    "servo_idmode_scan_single",
    'imu_data_',
    'Sensor_vector',
    'Worm_vector',
    'SysB',
    'data_address',
]


def get_func_address(path, name):
    address = None
    with open(path, 'rb') as stream:
        elf = ELFFile(stream)
        for section in elf.iter_sections():
            if isinstance(section, SymbolTableSection):
                for symbol in section.iter_symbols():
                    if symbol.name == name:
                        address = symbol.entry['st_value']
                        break
            if address:
                break
        else:
            raise RuntimeError('Failed to find {}'.format(name))
    return address


armh7_elf_alist = {name: get_func_address(kondoh7_elf(), name)
                   for name in armh7_variable_list}

servo_eeprom_params64 = {
    'fix_header': (1, 2),
    'stretch_gain': (3, 4),
    'speed': (5, 6),
    'punch': (7, 8),
    'dead_band': (9, 10),
    'dumping': (11, 12),
    'safe_timer': (13, 14),
    'mode_flag_b7slave_b4rotation_b3pwm_b1free_b0reverse': (15, 16),
    'pulse_max_limit': (17, 18, 19, 20),
    'pulse_min_limit': (21, 22, 23, 24),
    'fix_dont_change_25': (25, 26),
    'ics_baud_rate_10_115200_00_1250000': (27, 28),
    'temperature_limit': (29, 30),
    'current_limit': (31, 32),
    'fix_dont_change_33': (33, 34),
    'fix_dont_change_35': (35, 36),
    'fix_dont_change_37': (37, 38),
    'fix_dont_change_39': (39, 40),
    'fix_dont_change_41': (41, 42),
    'fix_dont_change_43': (43, 44),
    'fix_dont_change_45': (45, 46),
    'fix_dont_change_47': (47, 48),
    'fix_dont_change_49': (49, 50),
    'response': (51, 52),
    'user_offset': (53, 54),
    'fix_dont_change_55': (55, 56),
    'servo_id': (57, 58),
    'stretch_1': (59, 60),
    'stretch_2': (61, 62),
    'stretch_3': (63, 64),
}


def ctype_to_struct_format(c_type):
    if c_type == ':integer':
        return 'i'  # or 'I' for unsigned
    elif c_type == ':byte':
        return 'b'  # or 'B' for unsigned
    elif c_type == ':short':
        return 'h'  # or 'H' for unsigned
    elif c_type == ':float':
        return 'f'
    elif c_type == ':double':
        return 'd'
    # Add more mappings as needed


def slot_vector_from_str(byte_str, cls, slot_name):
    length = c_vector[cls.__name__]
    vec = [None] * length
    cnt = 1
    typ = cls.__fields_types__[slot_name].c_type
    tsize = c_type_to_size(typ)
    offset = cls.__fields_types__[slot_name].offset
    esize = cls.__fields_types__[slot_name].c_type
    fmt = ctype_to_struct_format(typ)
    for i in range(length):
        if cnt == 1:
            v = struct.unpack_from(fmt, byte_str, offset + i * esize)[0]
            vec[i] = v
        else:
            lst = []
            for j in range(cnt):
                v = struct.unpack_from(
                    fmt, byte_str, offset + i * tsize + j * esize)[0]
                lst.append(v)
            vec[i] = lst
    return vec


class ARMH7Interface(object):

    def __init__(self):
        self.serial = None
        self.id_vector = None
        self.servo_sorted_ids = None
        self.worm_sorted_ids = None

    def __del__(self):
        self.close()

    def open(self, port='/dev/ttyUSB1', baudrate=1000000, timeout=0.01):
        """Opens a serial connection to the ARMH7 device.

        Parameters
        ----------
        port : str
            The port name to connect to.
        baudrate : int
            The baud rate for the serial connection.
        timeout : float, optional
            The timeout for the serial connection in seconds (default is 0.01).

        Returns
        -------
        None

        Raises
        ------
        serial.SerialException
            If there is an error opening the serial port.
        """
        try:
            self.serial = serial.Serial(port, baudrate, timeout=timeout)
            print(f"Opened {port} at {baudrate} baud")
        except serial.SerialException as e:
            print(f"Error opening serial port: {e}")
        return self.check_ack()

    def close(self):
        if self.serial:
            self.serial.close()

    def serial_write(self, byte_list):
        if self.serial is None:
            raise RuntimeError('Serial is not opened.')

        data_to_send = bytes(byte_list)
        try:
            self.serial.write(data_to_send)
        except serial.SerialException as e:
            print(f"Error sending data: {e}")
        return self.serial_read()

    def serial_read(self):
        if self.serial is None:
            raise RuntimeError('Serial is not opened.')

        ret = ''
        while len(ret) == 0:
            try:
                ret = self.serial.read_until()
            except serial.SerialException as e:
                print(f"Error reading data: {e}")
                return None

        while len(ret) > 0 and ret[0] != len(ret):
            try:
                ret += self.serial.read_until()
            except serial.SerialException as e:
                print(f"Error reading data: {e}")
                return None
        return ret[1:len(ret) - 1]

    def get_ack(self):
        byte_list = [0x04, 0xFE, 0x06, 0x08]
        return self.serial_write(byte_list)

    def check_ack(self):
        ack_byte_list = self.get_ack()
        return ack_byte_list[1] == 0x06

    def memory_read_aux(self, addr, length):
        """Memory Read Aux function"""
        cnt = 1
        e_size = length
        skip_size = 0
        n = 11
        byte_list = [0] * n
        byte_list[0] = n
        byte_list[1] = 0xFB  # MREADV_OP
        byte_list[2] = addr & 0xFF
        byte_list[3] = (addr >> 8) & 0xFF
        byte_list[4] = (addr >> 16) & 0xFF
        byte_list[5] = (addr >> 24) & 0xFF
        byte_list[6] = cnt
        byte_list[7] = e_size
        byte_list[8] = skip_size & 0xFF
        byte_list[9] = (skip_size >> 8) & 0xFF
        byte_list[10] = rcb4_checksum(byte_list)
        return self.serial_write(byte_list)

    def memory_read(self, addr, length):
        limit = 250
        if length < limit:
            return self.memory_read_aux(addr, length)
        elif length < 2 * limit:
            return self.memory_read_aux(addr, limit) \
                + self.memory_read_aux(addr + limit, length - limit)
        else:
            return self.memory_read_aux(addr, limit) \
                + self.memory_read_aux(addr + limit, limit) \
                + self.memory_read_aux(addr + 2 * limit, length - 2 * limit)

    def memory_cstruct(self, cls, v_idx=0, addr=None, size=None):
        if addr is None:
            addr = armh7_elf_alist[cls.__name__]
        if size is None:
            size = cls.size
        buf = self.memory_read((size * v_idx) + addr, size)
        return cls(buf)

    def memory_write(self, addr, length, data):
        cnt = 1
        e_size = length
        skip_size = 0
        n = length + 11
        byte_list = bytearray(n)
        byte_list[0] = n
        byte_list[1] = 0xFC  # MWRITEV_OP
        byte_list[2:6] = addr.to_bytes(4, byteorder='little')
        byte_list[6] = cnt
        byte_list[7] = e_size
        byte_list[8:10] = skip_size.to_bytes(2, byteorder='little')
        for i in range(length):
            byte_list[10 + i] = data[i]
        byte_list[10 + length] = rcb4_checksum(byte_list[0:n-1])
        return self.serial_write(byte_list)

    def cfunc_call(self, func_string, *args):
        addr = armh7_elf_alist[func_string]
        argc = len(*args)
        n = 8 + 4 * argc
        byte_list = bytearray(n)
        byte_list[0] = n
        byte_list[1] = 0xfa
        byte_list[2:6] = addr.to_bytes(4, byteorder='little')
        byte_list[6] = argc
        for i in range(argc):
            byte_list[7 + i * 4] = args[i].to_bytes(4, byteorder='little')
        byte_list[n - 1] = rcb4_checksum(byte_list[0:n-1])
        return self.serial_write(byte_list)

    def write_cls_alist(self, cls, idx, slot_name, vec):
        baseaddr = armh7_elf_alist[cls.__name__]
        cls_size = cls.size
        typ = cls.__fields_types__[slot_name].c_type
        slot_size = c_type_to_size(typ)
        slot_offset = cls.__fields_types__[slot_name].offset
        cls.__fields_types__[slot_name].c_type
        cnt = 1
        addr = baseaddr + (idx * cls_size) + slot_offset
        data = bytearray(slot_size)

        if cnt == 1:
            v = None
            if isinstance(vec, list):
                v = vec[0]
            else:
                v = vec
            if typ == 'float':
                byte_data = struct.pack('f', v)
                byte_data = struct.unpack('4B', byte_data)
            elif typ == 'uint16':
                byte_data = struct.pack('H', v)
                byte_data = struct.unpack('BB', byte_data)
            elif typ == 'uint8':
                # Unpacking a single byte.
                byte_data = struct.pack('B', v)
                byte_data = struct.unpack('B', byte_data)
            else:
                raise RuntimeError('not implemented typ {}'.format(typ))
            data[0:len(byte_data)] = byte_data
        else:
            raise NotImplementedError
        return self.memory_write(addr, slot_size, data)

    def read_cstruct_slot_v(self, cls, slot_name):
        vcnt = c_vector[cls.__name__]
        addr = armh7_elf_alist[cls.__name__]
        cls_size = cls.size
        # import ipdb
        # ipdb.set_trace()
        slot_offset = cls.__fields_types__[slot_name].offset
        element_size = c_type_to_size(cls.__fields_types__[slot_name].c_type)
        n = 11
        byte_list = np.zeros(n, dtype=np.uint8)
        byte_list[0] = n
        byte_list[1] = 0xFB  # MREADV_OP
        byte_list[2:6] = np.array([(addr + slot_offset) >> (i * 8) & 0xff
                                   for i in range(4)], dtype=np.uint8)
        byte_list[6] = vcnt
        byte_list[7] = element_size
        byte_list[8] = cls_size
        byte_list[n - 1] = rcb4_checksum(byte_list)
        b = self.serial_write(byte_list)
        return np.frombuffer(b, dtype=np.uint16)

    def read_jointbase_sensor_ids(self):
        if self.id_vector is None:
            ret = []
            for i in range(max_sensor_num):
                sensor = self.memory_cstruct(
                    SensorbaseStruct, i)
                port = sensor.port
                id = sensor.id
                if port > 0 and id == (i + sensor_sidx) // 2:
                    ret.append(i + sensor_sidx)
            self.id_vector = list(sorted(ret))
        return self.id_vector

    def reference_angle_vector(self):
        return self.read_cstruct_slot_v(
            ServoStruct, slot_name='ref_angle')

    def angle_vector(self):
        return self.read_cstruct_slot_v(ServoStruct,
                                        slot_name='current_angle')

    def search_servo_ids(self):
        indices = []
        for idx in range(rcb4_dof):
            servo = self.memory_cstruct(ServoStruct, idx)
            if servo.flag > 0:
                indices.append(idx)
        self.servo_sorted_ids = indices
        return indices

    def hold(self, servo_ids=None):
        if servo_ids is None:
            servo_ids = self.servo_sorted_ids
        servo_vector = [32767] * len(servo_ids)
        return self.servo_angle_vector(servo_ids,
                                       servo_vector,
                                       velocity=1000)

    def free(self, servo_ids=None):
        if servo_ids is None:
            servo_ids = self.servo_sorted_ids
        servo_vector = [32768] * len(servo_ids)
        return self.servo_angle_vector(servo_ids,
                                       servo_vector,
                                       velocity=1000)

    def neutral(self, servo_ids=None, velocity=1000):
        if servo_ids is None:
            servo_ids = self.servo_sorted_ids
        servo_vector = [7500] * len(servo_ids)
        return self.servo_angle_vector(servo_ids,
                                       servo_vector,
                                       velocity=velocity)

    def servo_angle_vector(self, servo_ids, servo_vector, velocity=1000):
        byte_list = [CommandTypes.MultiServoSingleVelocity.value] \
            + rcb4_servo_ids_to_5bytes(servo_ids) \
            + [rcb4_velocity(velocity)] \
            + rcb4_servo_positions(servo_ids, servo_vector)
        byte_list.insert(0, 2 + len(byte_list))
        byte_list.append(rcb4_checksum(byte_list))
        return self.serial_write(byte_list)

    def servo_param64(self, sid, param_names=None):
        v = self.memory_cstruct(ServoStruct, sid)
        param_values = {}
        if param_names is None:
            param_names = list(servo_eeprom_params64.keys())
        for param_name in param_names:
            indices = servo_eeprom_params64[param_name]
            param_value = four_bit_to_num(indices, v.params)
            param_values[param_name] = param_value
        return param_values

    def read_stretch(self, servo_ids=None):
        if servo_ids is None:
            servo_ids = self.servo_sorted_ids
        return [self.servo_param64(sid, ['stretch_gain'])['stretch_gain'] // 2
                for sid in servo_ids]

    def send_stretch(self, value=127, servo_ids=None):
        if servo_ids is None:
            servo_ids = self.servo_sorted_ids
        if not isinstance(value, list) or not isinstance(value, tuple):
            value = [value] * len(servo_ids)
        byte_list = [CommandTypes.ServoParam.value] \
            + rcb4_servo_ids_to_5bytes(servo_ids) \
            + [ServoParams.Stretch.value] \
            + rcb4_servo_svector(servo_ids, value)
        byte_list.insert(0, 2 + len(byte_list))
        byte_list.append(rcb4_checksum(byte_list))
        return self.serial_write(byte_list)

    def read_quaternion(self):
        cs = self.memory_cstruct(Madgwick, 0)
        return np.array([cs.q0, cs.q1, cs.q2, cs.q3], dtype=np.float32)

    def read_rpy(self):
        cs = self.memory_cstruct(Madgwick, 0)
        return [cs.roll, cs.pitch, cs.yaw]

    def gyro_norm_vector(self):
        g = self.memory_cstruct(Madgwick, 0).gyro
        n = np.sqrt(g[0] ** 2 + g[1] ** 2 + g[2] ** 2)
        return (n, g)

    def set_cstruct_slot(self, cls, idx, slot_name, v):
        baseaddr = armh7_elf_alist[cls.__name__]
        cls_size = cls.size
        typ = cls.__fields_types__[slot_name].c_type
        slot_size = c_type_to_size(typ)
        slot_offset = cls.__fields_types__[slot_name].offset
        cls.__fields_types__[slot_name].c_type
        addr = baseaddr + (idx * cls_size) + slot_offset
        bytes = bytearray(slot_size)

        if typ == 'float':
            byte_data = struct.pack('f', v)
            byte_data = struct.unpack('4B', byte_data)
        elif typ == 'uint16':
            byte_data = struct.pack('H', v)
            byte_data = struct.unpack('BB', byte_data)
        elif typ == 'uint8':
            byte_data = [v]
        else:
            raise RuntimeError('not implemented typ {}'.format(typ))
        bytes[0:len(byte_data)] = byte_data
        return self.memory_write(addr, slot_size, bytes)

    def search_wheel_sids(self):
        indices = []
        for idx in self.servo_sorted_ids:
            servo = self.memory_cstruct(ServoStruct, idx)
            if servo.rotation > 0:
                indices.append(idx)
            if servo.feedback > 0:
                self.set_cstruct_slot(ServoStruct, idx, 'feedback', 0)
        self.wheel_servo_sorted_ids = sorted(indices)
        return indices

    def search_worm_ids(self):
        indices = []
        for idx in range(max_sensor_num):
            worm = self.memory_cstruct(WormmoduleStruct, idx)
            if worm.module_type == 1:
                indices.append(idx)
        self.worm_sorted_ids = indices
        return indices

    def read_worm_angle(self, idx=0):
        if not 0 <= idx < max_sensor_num:
            print(
                f"Error: The worm servo index {idx} is out of the valid range."
                " Please provide an index between 0 and {max_sensor_num - 1}.")
        if self.worm_sorted_ids is None:
            self.worm_sorted_ids = self.search_worm_ids()
        if idx not in self.worm_sorted_ids:
            print(
                f"Error: The worm servo index {idx} is out of the valid range."
                f" Valid indices are: {self.worm_sorted_ids}. "
                'Please provide an index from this list.'
            )
        return self.memory_cstruct(WormmoduleStruct, idx).present_angle

    def send_worm_angle_and_threshold(
            self, worm_idx=0, angle=0, threshold=30, threshold_scale=1.0,
            sign=1):
        angle_lst = [angle]
        th_lst = [threshold]
        th_scale_lst = [threshold_scale]
        if not 0 <= worm_idx < max_sensor_num:
            print(f"invalid argument worm_idx={worm_idx}")
        else:
            worm = self.memory_cstruct(WormmoduleStruct, worm_idx)
            self.write_cls_alist(WormmoduleStruct, worm_idx,
                                 'ref_angle', angle_lst)
            self.write_cls_alist(WormmoduleStruct, worm_idx,
                                 'thleshold', th_lst)
            self.write_cls_alist(WormmoduleStruct, worm_idx,
                                 'thleshold_scale', th_scale_lst)
            self.servo_angle_vector(
                [worm.servo_id], [sign * 135 * 30 + 7500], velocity=10)
            worm = self.memory_cstruct(WormmoduleStruct, worm_idx)
            return worm

    def send_worm_calib_data(
            self, worm_idx, servo_idx=None, sensor_idx=None,
            module_type=None, magenc_offset=None,
            upper_limit=69.0, thleshold_scale=5.0,
            timeout_time_scale=1.25, gear_ratio=20.0):
        # Check for valid worm_idx
        if not 0 <= worm_idx < max_sensor_num:
            print(f"Invalid argument worm_idx={worm_idx}")
            return

        # Print the formatted information
        print(f"send worm_idx: {worm_idx}, module_type: {module_type}"
              f", servo_idx: {servo_idx} sensor_idx: {sensor_idx}")
        print(f"magenc_offset: {magenc_offset}, upper_limit: {upper_limit}, "
              f"thleshold_scale: {thleshold_scale}, "
              f"timeout_time_scale: {timeout_time_scale}"
              f", gear_ratio: {gear_ratio}")

        # Write the parameters to the wormmodule vector cstruct
        if module_type is not None:
            self.write_cls_alist(
                WormmoduleStruct, worm_idx, 'module_type', [module_type])
        if servo_idx is not None:
            self.write_cls_alist(
                WormmoduleStruct, worm_idx, 'servo_id', [servo_idx])
        if sensor_idx is not None:
            self.write_cls_alist(
                WormmoduleStruct, worm_idx, 'sensor_id', [sensor_idx])
        self.write_cls_alist(WormmoduleStruct, worm_idx, 'move_state', [0])
        if magenc_offset is not None:
            self.write_cls_alist(WormmoduleStruct, worm_idx,
                                 'magenc_init', [magenc_offset % (2 ** 14)])
        if upper_limit is not None:
            self.write_cls_alist(WormmoduleStruct, worm_idx,
                                 'linear_upper_limit', [upper_limit])
        if thleshold_scale is not None:
            self.write_cls_alist(WormmoduleStruct, worm_idx,
                                 'thleshold_scale', [thleshold_scale])
        if timeout_time_scale is not None:
            self.write_cls_alist(WormmoduleStruct, worm_idx,
                                 'timeout_time_scale', [timeout_time_scale])
        if gear_ratio is not None:
            self.write_cls_alist(WormmoduleStruct, worm_idx, 'gear_ratio',
                                 [gear_ratio])
        return self.memory_cstruct(WormmoduleStruct, worm_idx)

    def buzzer(self):
        return self.cfunc_call('buzzer_init_sound', [])

    def write_to_flash(self):
        return self.cfunc_call('rom_to_flash', [])

    def set_data_address(self):
        self.set_sidata()
        self.set_sdata()
        self.set_edata()
        self.set_data_size()

    def set_sidata(self, sidata=None):
        sidata = sidata or armh7_elf_alist['_sidata']
        return self.cstruct_slot(DataAddress, '_sidata', sidata)

    def set_sdata(self, sdata=None):
        sdata = sdata or armh7_elf_alist['_sdata']
        return self.cstruct_slot(DataAddress, '_sdata', sdata)

    def set_edata(self, edata=None):
        edata = edata or armh7_elf_alist['_edata']
        return self.cstruct_slot(DataAddress, '_edata', edata)

    def set_data_size(self, sdata=None, edata=None):
        sdata = sdata or armh7_elf_alist['_sdata']
        edata = edata or armh7_elf_alist['uwTickPrio']
        return self.cstruct_slot(DataAddress, 'data_size', edata - sdata)

    def cstruct_slot(self, cls, slot_name, v=None):
        if v is not None:
            return self.write_cstruct_slot_v(cls, slot_name, v)
        return self.read_cstruct_slot_v(cls, slot_name)

    def write_cstruct_slot_v(self, cls, slot_name, vec):
        vcnt = c_vector[cls.__name__]
        addr = armh7_elf_alist[cls.__name__]
        skip_size = cls.size
        cnt = 1
        typ = cls.__fields_types__[slot_name].c_type
        tsize = c_type_to_size(typ)
        offset = cls.__fields_types__[slot_name].offset
        esize = cls.__fields_types__[slot_name].c_type

        n = 11 + tsize * vcnt
        if n > 240:
            print(f"n={n} should be less than 240")
            return

        byte_list = bytearray(n)
        byte_list[0] = n
        byte_list[1] = 0xFC  # MWRITEV_OP
        struct.pack_into('I', byte_list, 2, addr + offset)
        byte_list[6] = vcnt
        byte_list[7] = tsize
        struct.pack_into('H', byte_list, 8, skip_size)

        for i in range(vcnt):
            if cnt == 1:
                v = vec[i]
                if not isinstance(v, (int, float)):
                    v = v[0] if len(v) > 1 else v
                if typ in (':integer', ':byte', ':short'):
                    v = round(v)
                if typ in (':float', ':double'):
                    struct.pack_into('f', byte_list, 10 + i * esize, v)
                else:
                    struct.pack_into('I', byte_list, 10 + i * esize, v)
            else:
                for j in range(cnt):
                    v = vec[i][j]
                    if typ in (':integer', ':byte', ':short'):
                        v = round(v)
                    if typ in (':float', ':double'):
                        struct.pack_into('f', byte_list,
                                         10 + i * tsize + j * esize, v)
                    else:
                        struct.pack_into('I', byte_list,
                                         10 + i * tsize + j * esize, v)

        byte_list[n - 1] = rcb4_checksum(byte_list)
        s = self.serial_write(byte_list)
        return slot_vector_from_str(s, cls, slot_name)

    def read_jb_cstruct(self, idx):
        return self.memory_cstruct(
            SensorbaseStruct, idx - sensor_sidx)

    def all_jointbase_sensors(self):
        if self.id_vector is None:
            self.read_jointbase_sensor_ids()
        return [self.read_jb_cstruct(idx)
                for idx in self.id_vector]


if __name__ == '__main__':
    interface = ARMH7Interface()
    print(interface.open())
    indices = interface.search_servo_ids()
    worm_indices = interface.search_worm_ids()
    interface.search_wheel_sids()