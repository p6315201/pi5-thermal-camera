#!/usr/bin/python3

SITL=False

import time
import os,fcntl
import math
import socket
from yamspy import MSPy

serial_port = "/dev/serial0"


def get6(x):
    chval = [1100,1300,1500,1600,1800]
    i = 0
    while i<len(chval):
        if(chval[i] > x):
            break
        i = i + 1
    return i

def get2zoom(x):
    if(x<1500):
        i = 1
    else:
        i = 2
    return i

def getzoomandshut(x):
    zval = 0
    sval = 0
    if(x<1100):
        zval = 1
        sval = 0
    elif((1100<x)and(x<1300)):
        zval = 1
        sval = 1
    elif((1600<x)and(x<1800)):
        zval = 2
        sval = 0
    elif(1800<x):
        zval = 2
        sval = 1
    return zval,sval


def get3(x):
    chval = [1300,1800]
    i = 0
    while i<len(chval):
        if(chval[i] > x):
            break
        i = i + 1
    return i


def get7contrast(x):
    chval = [1100,1300,1480,1520,1600,1800]
    # chrez = [60,90,108,128,148,168,188]
    chrez = [48,58,68,78,88,98,108]
    i = 0
    while i<len(chval):
        if(chval[i] > x):
            break
        i = i + 1
    return chrez[i]


def get16brightness(x):
    chval = [1030,1100,1160,1230,1300,1360,1430,1500,1560,1630,1700,1760,1830,1900,1960]
    chrez = [48,58,68,78,88,98,108,118,128,138,148,158,168,178,188,198]
    i = 0
    while i<len(chval):
        if(chval[i] > x):
            break
        i = i + 1
    return chrez[i]


def get_uni_contr(x):
    chval = [1100,1150,1200,1250,1300,1350,1400,1450,1500,1550,1600,1750,1800,1850,1900]
    chrez = [60,65,70,75,80,85,90,95,100,105,110,115,120,125,130,135]
    i = 0
    while i<len(chval):
        if(chval[i] > x):
            break
        i = i + 1
    return chrez[i]



def get_conf():
    try:
        file = open("/home/pi/config.txt")
    except FileNotFoundError:
        file.close()
        return 2, 58, 80
    text = file.read().split('\n')
    print(text)
    try:
        static_agc = text[0].split(' ')[1]
        static_birght = text[1].split(' ')[1]
        static_contr = text[2].split(' ')[1]
    except:
        file.close()
        return 2, 58, 80

    print(f'read {static_agc} {static_birght} {static_contr}')
    file.close()
    return static_agc, static_birght, static_contr


def write_conf(a, b, c):
    #file = open("/home/pi/config.txt", 'w+')
    # wanted_text = f'agc {a}\nbrightness {b}\ncontrast {c}'
    #wanted_text = 'a ' + str(a) + '\nb ' + str(b) + '\nc ' + str(c)
    # wanted_text = f'sudo echo "agc {a}\nbrightness {b}\ncontrast {c}" > /root/config.txt'
    # wanted_text = 'sudo echo "agc {a}\nbrightness {b}\ncontrast {c}" > /root/config.txt'
    wanted_text = 'echo "aaa" > /home/pi/config.txt'
    os.system(wanted_text)
    #file.write(wanted_text)
    #file.close()




if __name__ == "__main__":

    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_socket.settimeout(1.0)
#    message = b'img 100 150'
    addr = ("127.0.0.1", 1111)
#    client_socket.sendto(message, addr)

    time.sleep(0.33)

    cur_img_agc = -1
    cur_img_cont = -1
    cur_img_br = -1
    cur_shut_do = -1

    time_start = time.time()
    exit_flag = 0

    # static_bright = 48
    # static_contr  = 80
    # static_agc = 1
    static_agc, static_bright, static_contr = get_conf()
    message = 'img '+str(static_bright)+' '+str(static_contr)+' '+str(static_agc)
    client_socket.sendto(str.encode(message), addr)

    cur_img_agc, cur_img_br, cur_img_cont = static_agc, static_bright, static_contr

    img_agc, img_cont = static_agc, static_contr

    time.sleep(0.33)

    shutter_last_time = 0
    shutt_state_do_1sec = True
    shutt_state_do_1sec_count = 5
    shutt_state_do_1sec_current_count = 0
    shutt_state_do_first_jerk = False
    shutt_state_do_1sec = 60

    conf_time_save = 5
    conf_last_time = 0

    tx16s_agc_pwm = 0
    tx16s_contr_pwm = 0
    cur_tx16s_agc_pwm = 0
    cur_tx16s_contr_pwm = 0

    we_use_tx16 = False

    with MSPy(device=serial_port, loglevel='INFO', baudrate=115200) as board:

        while(0 ==exit_flag):
            time.sleep(0.2)
            if board.send_RAW_msg(MSPy.MSPCodes['MSP_RC'], data=[]):
                dataHandler = board.receive_msg()
                board.process_recv_data(dataHandler)
                chann = board.RC['channels']

                shutt = get3(chann[6])
                img_br = get7contrast(chann[8])

                tx16s_agc_pwm = chann[12]
                tx16s_contr_pwm = chann[5]

                if cur_tx16s_agc_pwm == 0:
                    cur_tx16s_agc_pwm = tx16s_agc_pwm
                    # img_agc = static_agc
                # elif cur_tx16s_agc_pwm != 0 and cur_tx16s_agc_pwm != 1500 and cur_tx16s_agc_pwm != tx16s_agc_pwm:
                elif cur_tx16s_agc_pwm != 0 and cur_tx16s_agc_pwm != tx16s_agc_pwm:
                    # cur_tx16s_agc_pwm = tx16s_agc_pwm
                    cur_tx16s_agc_pwm = tx16s_agc_pwm
                    img_agc = get6(cur_tx16s_agc_pwm)
                    we_use_tx16 = True
                # else:
                #     img_agc = static_agc

                if cur_tx16s_contr_pwm == 0:
                    cur_tx16s_contr_pwm = tx16s_contr_pwm
                    # img_cont = static_contr
                # elif cur_tx16s_contr_pwm != 0 and cur_tx16s_contr_pwm != 1500 and cur_tx16s_contr_pwm != tx16s_contr_pwm:
                elif cur_tx16s_contr_pwm != 0 and cur_tx16s_contr_pwm != tx16s_contr_pwm:
                    # cur_tx16s_contr_pwm = tx16s_contr_pwm
                    cur_tx16s_contr_pwm = tx16s_contr_pwm
                    img_cont = get_uni_contr(cur_tx16s_contr_pwm)
                    we_use_tx16 = True
                # else:
                #     img_cont = static_contr

                if cur_img_br != img_br or cur_img_cont != img_cont or cur_img_agc != img_agc:
                    cur_img_br = img_br
                    cur_img_cont = img_cont
                    cur_img_agc = img_agc

                    message = 'img '+str(cur_img_br)+' '+str(cur_img_cont)+' '+str(cur_img_agc)
                    client_socket.sendto(str.encode(message), addr)
                    # write_conf(cur_img_agc, cur_img_br, cur_img_cont)
                    # wanted_text = 'sudo echo "aaa" > /home/pi/config.txt'
                    # os.system(wanted_text)

                if shutt != cur_shut_do:
                    cur_shut_do = shutt
                    if time.time() - shutter_last_time > 5.0:

                        message = 'shut'
                        client_socket.sendto(str.encode(message), addr)
                        shutter_last_time = time.time()

                        # if not shutt_state_do_first_jerk:
                        shutt_state_do_first_jerk = True
                        time.sleep(1)

                        message = 'img '+str(cur_img_br)+' '+str(cur_img_cont)+' '+str(cur_img_agc)
                        client_socket.sendto(str.encode(message), addr)
                        
                        if shutt_state_do_1sec:
                            shutt_state_do_1sec_current_count += 1

                if shutt_state_do_1sec:
                    if shutt_state_do_1sec_current_count != shutt_state_do_1sec_count:
                        if time.time() - shutter_last_time > shutt_state_do_1sec:
                            message = 'shut'
                            client_socket.sendto(str.encode(message), addr)
                            shutter_last_time = time.time()
                            shutt_state_do_1sec_current_count += 1
                    if shutt_state_do_1sec_count <= shutt_state_do_1sec_current_count:
                        shutt_state_do_1sec = False
                
                if time.time() - conf_last_time > conf_time_save:
                    conf_last_time = time.time()
                    write_conf(cur_img_agc, cur_img_br, cur_img_cont)
 
