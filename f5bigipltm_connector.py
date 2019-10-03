# File: f5bigipltm_connector.py
#
# Copyright (c) 2019 Splunk Inc.
#
# SPLUNK CONFIDENTIAL - Use or disclosure of this material in whole or in part
# without a valid written license from Splunk Inc. is PROHIBITED.

# Phantom App imports
import phantom.app as phantom
from phantom.base_connector import BaseConnector
from phantom.action_result import ActionResult

# Usage of the consts file is recommended
# from f5bigipltm_consts import *
import requests
import json
from bs4 import BeautifulSoup


class RetVal(tuple):
    def __new__(cls, val1, val2=None):
        return tuple.__new__(RetVal, (val1, val2))


class F5BigipLtmConnector(BaseConnector):

    def __init__(self):

        # Call the BaseConnectors init first
        super(F5BigipLtmConnector, self).__init__()

        self._auth = None
        self._state = None
        self._base_url = None

    def _process_empty_response(self, response, action_result):

        if response.status_code == 200:
            return RetVal(phantom.APP_SUCCESS, {})

        return RetVal(action_result.set_status(phantom.APP_ERROR, "Empty response and no information in the header"), None)

    def _process_html_response(self, response, action_result):

        # An html response, treat it like an error
        status_code = response.status_code

        if (status_code == 200):
            return RetVal(phantom.APP_SUCCESS, response.text)

        try:
            soup = BeautifulSoup(response.text, "html.parser")
            error_text = soup.text
            split_lines = error_text.split('\n')
            split_lines = [x.strip() for x in split_lines if x.strip()]
            error_text = '\n'.join(split_lines)
        except:
            error_text = "Cannot parse error details"

        message = "Status Code: {0}. Data from server:\n{1}\n".format(status_code,
                error_text)

        message = message.replace(u'{', '{{').replace(u'}', '}}')

        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _process_json_response(self, r, action_result):

        # Try a json parse
        try:
            resp_json = r.json()
        except Exception as e:
            return RetVal(action_result.set_status(phantom.APP_ERROR, "Unable to parse JSON response. Error: {0}".format(str(e))), None)

        # Please specify the status codes here
        if 200 <= r.status_code < 399:
            return RetVal(phantom.APP_SUCCESS, resp_json)

        # You should process the error returned in the json
        message = "Error from server. Status Code: {0} Data from server: {1}".format(
                r.status_code, r.text.replace(u'{', '{{').replace(u'}', '}}'))

        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _process_response(self, r, action_result):

        # store the r_text in debug data, it will get dumped in the logs if the action fails
        if hasattr(action_result, 'add_debug_data'):
            action_result.add_debug_data({'r_status_code': r.status_code})
            action_result.add_debug_data({'r_text': r.text})
            action_result.add_debug_data({'r_headers': r.headers})

        # Process each 'Content-Type' of response separately

        # Process a json response
        if 'json' in r.headers.get('Content-Type', ''):
            if not r.text:
                return self._process_empty_response(r, action_result)
            else:
                return self._process_json_response(r, action_result)

        # Process an HTML response, Do this no matter what the api talks.
        # There is a high chance of a PROXY in between phantom and the rest of
        # world, in case of errors, PROXY's return HTML, this function parses
        # the error and adds it to the action_result.
        if 'html' in r.headers.get('Content-Type', ''):
            return self._process_html_response(r, action_result)

        # it's not content-type that is to be parsed, handle an empty response
        if not r.text:
            return self._process_empty_response(r, action_result)

        # everything else is actually an error at this point
        message = "Can't process response from server. Status Code: {0} Data from server: {1}".format(
                r.status_code, r.text.replace('{', '{{').replace('}', '}}'))

        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _make_rest_call(self, endpoint, action_result, method="get", **kwargs):

        config = self.get_config()

        resp_json = None

        try:
            request_func = getattr(requests, method)
        except AttributeError:
            return RetVal(action_result.set_status(phantom.APP_ERROR, "Invalid method: {0}".format(method)), resp_json)

        # Create a URL to connect to
        url = self._base_url + endpoint

        try:
            r = request_func(
                            url,
                            auth=self._auth,
                            verify=config.get('verify_server_cert', False),
                            **kwargs)
        except Exception as e:
            return RetVal(action_result.set_status( phantom.APP_ERROR, "Error Connecting to server. Details: {0}".format(str(e))), resp_json)

        return self._process_response(r, action_result)

    def _handle_test_connectivity(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        self.save_progress("Querying info about F5 BIG-IP LTM instance to test connectivity")

        ret_val, response = self._make_rest_call('/mgmt/tm/ltm', action_result, params=None, headers=None)

        if (phantom.is_fail(ret_val)):
            self.save_progress("Test Connectivity Failed.")
            return action_result.get_status()

        # Return success
        self.save_progress("Test Connectivity Passed")
        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_remove_node(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        pool_name = param['pool_name']
        node_name = param['node_name']
        port = param['port']

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/pool/{0}/members/{1}:{2}'.format(pool_name, node_name, port), action_result, method="delete")

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        action_result.add_data({})

        summary = action_result.update_summary({})
        summary['node_name'] = pool_name
        summary['port'] = port
        summary['pool_name'] = pool_name

        return action_result.set_status(phantom.APP_SUCCESS, "Node successfully removed from pool".format(pool_name))

    def _handle_add_node(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        node_name = param['node_name']
        port = param['port']
        partition_name = param['partition_name']
        pool_name = param['pool_name']

        # make rest call
        ret_val, response = self._make_rest_call(
            '/mgmt/tm/ltm/pool/{0}/members'.format(pool_name),
            action_result, method="post", json={"name": "/{0}/{1}:{2}".format(partition_name, node_name, port)})

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        action_result.add_data(response)

        summary = action_result.update_summary({})
        summary['node_name'] = response['name']
        summary['port'] = port
        summary['pool_name'] = pool_name

        return action_result.set_status(phantom.APP_SUCCESS, "Node successfully added to pool")

    def _handle_create_node(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        node = param['node_name']
        partition = param['partition_name']
        address = param['ip_address']

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/node',
        action_result, method="post", json={"name": node, "partition":
        partition, "address": address})

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        action_result.add_data(response)

        summary = action_result.update_summary({})
        summary['node_name'] = response['name']

        return action_result.set_status(phantom.APP_SUCCESS, "Node successfully created")

    def _handle_delete_node(self, param):
        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        node_name = param['node_name']

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/node/{0}'.format(node_name), action_result, method="delete")

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        action_result.add_data({})

        summary = action_result.update_summary({})
        summary['node_name'] = node_name

        return action_result.set_status(phantom.APP_SUCCESS, "Successfully deleted node")

    def _handle_disable_node(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        node_name = param['node_name']
        param['session'] = 'user-disabled'

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/node/{0}'.format(node_name), action_result, method="patch", json={'session': 'user-disabled'})

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        # Add the response into the data section
        action_result.add_data(response)

        summary = action_result.update_summary({})
        summary['node_name'] = node_name

        return action_result.set_status(phantom.APP_SUCCESS, "Successfully disabled node")

    def _handle_enable_node(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        node_name = param['node_name']
        param['session'] = 'user-enabled'

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/node/{0}'.format(node_name), action_result, method="patch", json={'session': 'user-enabled'})

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        # Add the response into the data section
        action_result.add_data(response)

        summary = action_result.update_summary({})
        summary['node_name'] = node_name

        return action_result.set_status(phantom.APP_SUCCESS, "Successfully enabled node")

    def _handle_describe_node(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        node_name = param['node_name']

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/node/{0}'.format(node_name), action_result)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        action_result.add_data(response)

        summary = action_result.update_summary({})
        summary['state'] = response['state']

        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_list_nodes(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/node', action_result)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        node_names = []

        for item in response['items']:
            action_result.add_data(item)
            if 'name' in item:
                node_names.append(item['name'])

        summary = action_result.update_summary({})
        summary['num_nodes'] = len(action_result.get_data())

        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_list_pools(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/pool', action_result)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        for item in response['items']:
            action_result.add_data(item)

        summary = action_result.update_summary({})
        summary['num_pools'] = len(action_result.get_data())

        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_create_pool(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        pool_name = param['pool_name']
        partition_name = param['partition_name']

        pool_description = param.get('pool_description')

        payload = { 'name': pool_name, 'partition': partition_name }
        if pool_description:
            payload['pool_description'] = pool_description

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/pool', action_result, method="post", json=payload)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        action_result.add_data(response)

        summary = action_result.update_summary({})
        summary['pool_name'] = pool_name
        summary['partition'] = partition_name
        summary['pool_description'] = pool_description

        return action_result.set_status(phantom.APP_SUCCESS, "Successfully created pool")

    def _handle_list_members(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        pool_name = param['pool_name']
        partition_name = param['partition_name']

        # make rest call
        ret_val, response = self._make_rest_call('/mgmt/tm/ltm/pool/~{0}~{1}/members'.format(partition_name, pool_name), action_result)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        members = []

        for item in response['items']:
            action_result.add_data(item)
            if 'name' in item:
                members.append(item['name'])

        summary = action_result.update_summary({})
        summary['num_members'] = len(action_result.get_data())
        summary['members'] = ','.join(members)

        return action_result.set_status(phantom.APP_SUCCESS, "Successfully listed pool members")

    def handle_action(self, param):

        ret_val = phantom.APP_SUCCESS

        # Get the action that we are supposed to execute for this App Run
        action_id = self.get_action_identifier()

        self.debug_print("action_id", self.get_action_identifier())

        if action_id == 'test_connectivity':
            ret_val = self._handle_test_connectivity(param)

        elif action_id == 'create_pool':
            ret_val = self._handle_create_pool(param)

        elif action_id == 'create_node':
            ret_val = self._handle_create_node(param)

        elif action_id == 'delete_node':
            ret_val = self._handle_delete_node(param)

        elif action_id == 'remove_node':
            ret_val = self._handle_remove_node(param)

        elif action_id == 'add_node':
            ret_val = self._handle_add_node(param)

        elif action_id == 'disable_node':
            ret_val = self._handle_disable_node(param)

        elif action_id == 'enable_node':
            ret_val = self._handle_enable_node(param)

        elif action_id == 'describe_node':
            ret_val = self._handle_describe_node(param)

        elif action_id == 'list_nodes':
            ret_val = self._handle_list_nodes(param)

        elif action_id == 'list_pools':
            ret_val = self._handle_list_pools(param)

        elif action_id == 'list_members':
            ret_val = self._handle_list_members(param)

        return ret_val

    def initialize(self):

        self._state = self.load_state()

        # get the asset config
        config = self.get_config()

        self._base_url = config['base_url']
        self._auth = (config['username'], config['password'])

        return phantom.APP_SUCCESS

    def finalize(self):

        # Save the state, this data is saved across actions and app upgrades
        self.save_state(self._state)
        return phantom.APP_SUCCESS


if __name__ == '__main__':

    import pudb
    import argparse

    pudb.set_trace()

    argparser = argparse.ArgumentParser()

    argparser.add_argument('input_test_json', help='Input Test JSON file')
    argparser.add_argument('-u', '--username', help='username', required=False)
    argparser.add_argument('-p', '--password', help='password', required=False)

    args = argparser.parse_args()
    session_id = None

    username = args.username
    password = args.password

    if (username is not None and password is None):

        # User specified a username but not a password, so ask
        import getpass
        password = getpass.getpass("Password: ")

    if (username and password):
        try:
            login_url = F5BigipLtmConnector._get_phantom_base_url() + '/login'

            print ("Accessing the Login page")
            r = requests.get(login_url, verify=False)
            csrftoken = r.cookies['csrftoken']

            data = dict()
            data['username'] = username
            data['password'] = password
            data['csrfmiddlewaretoken'] = csrftoken

            headers = dict()
            headers['Cookie'] = 'csrftoken=' + csrftoken
            headers['Referer'] = login_url

            print ("Logging into Platform to get the session id")
            r2 = requests.post(login_url, verify=False, data=data, headers=headers)
            session_id = r2.cookies['sessionid']
        except Exception as e:
            print ("Unable to get session id from the platform. Error: " + str(e))
            exit(1)

    with open(args.input_test_json) as f:
        in_json = f.read()
        in_json = json.loads(in_json)
        print(json.dumps(in_json, indent=4))

        connector = F5BigipLtmConnector()
        connector.print_progress_message = True

        if (session_id is not None):
            in_json['user_session_token'] = session_id
            connector._set_csrf_info(csrftoken, headers['Referer'])

        ret_val = connector._handle_action(json.dumps(in_json), None)
        print (json.dumps(json.loads(ret_val), indent=4))

    exit(0)
