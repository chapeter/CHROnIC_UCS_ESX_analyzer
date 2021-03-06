__author__ = 'Chad Peterson'
__email__ = 'chapeter@cisco.com'

from tinydb import TinyDB, Query
from HCL import getServerType_PID, getServerType, getServerModel, getProcessor, getOSVendor, getOSVersion, getFirmware
from HCL import hclSearch, lookupByPID
import pprint
from flask_api import FlaskAPI
from flask import request
import requests
import json
import ast
import os
import base64

app = FlaskAPI(__name__)


piddb = TinyDB('piddb.json')
item = Query()
busbaseurl = os.environ['CHRONICBUS']




def server_merge(ucs_list, esx_list):
    servers = []
    count = 0
    for esx in esx_list:
        print(esx['driverinfo'])
        if bool(esx['driverinfo']) == True:
            esx_ident_list = esx['otherIdentifyingInfo/identifierValue/~']
            for id in esx_ident_list:
                for ucs in ucs_list:
                    ucs_serial = ucs['@serial'][0]
                    if id == ucs_serial:
                        print("Building merged server object.  Matched on esx", id, "ucs", ucs_serial)
                        server = {}
                        server['ucs'] = ucs
                        server['id'] = count
                        server['esx'] = esx
                        count = count + 1
                        servers.append(server)
    pprint.pprint(servers)
    return servers




def buildHCL_os_version(fullName):
    formatedName = ""
    for i in fullName.split():
        if i == "ESXi":
            formatedName = formatedName + "vSphere "
        elif i.split(".")[-1] == "0":
            formatedName = formatedName + i.split(".")[0] + "." + i.split(".")[1]
        #TODO build a check for U1 U2 type verisons

    return formatedName

def buildHCL_processor_name(processorFull):
    #example     "PROCESSOR": "Intel Xeon E5-2600 Series processors"
    print(processorFull)
    if "E5-26" in processorFull:
        if "v2" in processorFull:
            print(processorFull, "is a Intel Xeon E5-2600 v2 Series processors")
            return "Intel Xeon E5-2600 v2 Series processors"
        else:
            print(processorFull, "is a Intel Xeon E5-2600 Series processors")
            return "Intel Xeon E5-2600 Series processors"
    else:
        print("unsupported processor")
        return "UNSUPPORTED"


def buildHCL_firmware_name(firmware):
    print("Formating firmware name from, " + firmware + " to " + firmware[:5] + ")")
    return (firmware[:5] + ")")

def buildHCL_enic_number(enic):
    print("Reformatting " + enic + "to " + enic.split()[-1])
    return enic.split()[-1]

def buildHCL_fnic_number(fnic):
    fnic_long = (fnic.split()[2])
    fnic_version = fnic_long.split("-")[0]
    print("Formating FNIC " + fnic + " to " + fnic_version)
    return fnic_version




def hclCheck(servers):

    for server in servers:
        #TODO write a check to make sure server PID in DB

        base_server_type = getServerType_PID(server['ucs']['@model'][0])
        #print(base_server_type)
        serverType = getServerType(base_server_type['server_type'])
        #print(serverType)
        serverModel = getServerModel(serverType['T_ID'], base_server_type['ID'])
        #print(serverModel)

        processor_hcl_name = buildHCL_processor_name(server['ucs']['computeBoard/processorUnit/@model'][0])
        processor = getProcessor(serverModel['T_ID'], processor_hcl_name)
        #print(processor)

        osvendor_name = (server['esx']['fullName/~'][0].split()[0])
        #TODO if not VMware execption

        osVendor = getOSVendor(processor['T_ID'], osvendor_name)
        #print(osVendor)

        osversion_name = buildHCL_os_version(server['esx']['fullName/~'][0])
        osVersion = getOSVersion(osVendor['T_ID'], osversion_name)
        #print(osVersion)
        firmware_hcl_name = buildHCL_firmware_name(server['ucs']['mgmtController/firmwareRunning/@version'][0])
        firmwareVersion = getFirmware(osVersion['T_ID'], firmware_hcl_name)
        #print(firmwareVersion)
        manageType = 'UCSM'
        adapterinfo = lookupByPID(server['ucs']['adaptorUnit/@model'][0])

        if firmwareVersion != "UNSUPPORTED":
            results = hclSearch(serverType['ID'], serverModel['ID'], processor['ID'], osVendor['ID'], osVersion['ID'],
                                firmwareVersion['ID'], manageType)
            #print(results[0]['HardwareTypes']['Adapters']['CNA'])
            CNAs = results[0]['HardwareTypes']['Adapters']['CNA']
            CNA_Table = {}
            for CNA in CNAs:
                if CNA['Model'] == adapterinfo['adapter']:
                    print("Found adapter " + adapterinfo['adapter'])
                    if CNA['Model'] not in CNA_Table:
                        CNA_Table[CNA['Model']] = {}

                    if "Ethernet" in CNA['DriverVersion']:
                        ENIC = CNA['DriverVersion'].split(" ")[0]
                        CNA_Table[CNA['Model']].update({'ENIC':ENIC})

                    if "Fibre Channel" in CNA['DriverVersion']:
                        FNIC = CNA['DriverVersion'].split(" ")[0]
                        CNA_Table[CNA['Model']].update({'FNIC':FNIC})
            print(CNA_Table)
            #print(CNA_Table)
            server['supported_enic'] = CNA_Table[adapterinfo['adapter']]['ENIC']
            server['supported_fnic'] = CNA_Table[adapterinfo['adapter']]['FNIC']
            server['firmware_status'] = "SUPPORTED"
        else:
            server['supported_enic'] = "UNSUPPORTED FIRMWARE"
            server['supported_fnic'] = "UNSUPPORTED FIRMWARE"
            server['firmware_status'] = "UNSUPPORTED"

        print(server['supported_enic'])
        print(server['supported_fnic'])

        #TODO - Need error handling for missing driver info
        enic = buildHCL_enic_number(server['esx']['driverinfo'][3])
        fnic = buildHCL_fnic_number(server['esx']['driverinfo'][1])
        if enic == server['supported_enic']:
            server['enic_status'] = "Supported"
        else:
            server['enic_status'] = "Unupported"

        if fnic == server['supported_enic']:
            server['fnic_status'] = "Supported"
        else:
            server['fnic_status'] = "Unsupported"

        #print("Updated Server to " + server)
    return servers

def collectServerInfo(channelid):
    ##TODO
    #url = "http://imapex-chronic-bus.green.browndogtech.com/api/get/{}/2".format(channelid)
    url = busbaseurl + "/api/get/{}/2".format(channelid)
    headers = {
        'cache-control': "no-cache",
    }

    print("collectServerInfo:", url)
    response = requests.request("GET", url, headers=headers).json()
    #print(response)

    ucs_servers = ""
    esx_servers = ""
    for item in response:
        msgresp = item['msgresp']
        if msgresp != "":
            msgresp = base64.b64decode(bytes(msgresp, "utf-8")).decode("ascii")
            msgresp = eval(msgresp)
            #msgresp = ast.literal_eval(msgresp)
        #print(msgresp)
        if 'ucs' in msgresp:
            ucs_servers = msgresp['ucs']
        elif 'vcenter' in msgresp:
            esx_servers = msgresp['vcenter']
        #print("Pass")

    print(ucs_servers)
    print(esx_servers)
    return({'ucs_servers':ucs_servers, 'esx_servers':esx_servers})


def writeToBus(checked_servers, channelid):
    newchannelid_base = channelid + "-report"
    #url = "http://imapex-chronic-bus.green.browndogtech.com/api/get"
    url = busbaseurl + "/api/get"
    response = requests.request("GET", url).json()

    print("Counting Reports")
    count = 0
    for channel in response.keys():
        if channelid in channel:
            count = count + 1
    print("Found {} Reports".format(count))


    #url = "http://imapex-chronic-bus.green.browndogtech.com/api/send/{0}-{1}".format(newchannelid_base, str(count))
    url = busbaseurl + "/api/send/{0}-{1}".format(newchannelid_base, str(count))

    print("Posting to {}".format(url))

    headers = {
        'content-type': "application/json",
        'cache-control': "no-cache"
    }

    payload = {
        "msgdata": checked_servers,
        "desc": "finished HCL report",
        "status": "2"}

    response = requests.request("POST", url, data=json.dumps(payload), headers=headers)
    print(response)
    return

def updateStatus(channelid):
    url = busbaseurl + "/api/get/{}/2".format(channelid)
    response = requests.request("GET", url).json()
    ids = []
    for item in response:
        ids.append(item['id'])

    for id in ids:
        url = busbaseurl + "/api/status/{}".format(id)
        payload = {'status':'3'}
        headers = {'content-type': "application/json"}
        response = requests.request("POST", url, data=json.dumps(payload), headers=headers)
        print(("changing message {} to 3").format(id), response)
    return

@app.route("/")
def hc():
    return("Healthy")

@app.route("/api/<channelid>", methods=['GET'])
def main(channelid):
    #channelid = request.data['channelid']
    formatted_servers = collectServerInfo(channelid)
    servers = server_merge(formatted_servers['ucs_servers'], formatted_servers['esx_servers'])
    checked_servers = hclCheck(servers)
    pprint.pprint(checked_servers)
    print("Writing to BUS on {}".format(channelid))
    writeToBus(checked_servers, channelid)

    return("Finished")

@app.route("/api/<channelid>", methods=['POST'])
def main_post(channelid):
    print("It's a POST:", channelid)
    print("json" ,request.get_json())
    data = request.get_json()
    if data['status'] == '2':
        main(channelid)
        updateStatus(channelid)
        return ("Finished")
    else:
        print("job not yet done...not doing anything")
        return("Finished")

    return("Finished")

#main('h86eK4Ds')



if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True)

