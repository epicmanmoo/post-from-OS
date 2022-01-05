import datetime
from fake_useragent import UserAgent
import pytumblr
import requests
from requests.structures import CaseInsensitiveDict
import time
from tinydb import TinyDB, Query


class _OpenSeaTransactionObject:  # an OpenSea transaction object which holds information about the object
    def __init__(self, name_, image_url_, eth_nft_price_, total_usd_cost_, link_, num_of_assets_, tx_hash_):
        self.tumblr_caption = None
        self.name = name_
        self.image_url = image_url_
        self.eth_nft_price = eth_nft_price_
        self.total_usd_cost = total_usd_cost_
        self.link = link_
        self.is_posted = False
        self.num_of_assets = num_of_assets_
        self.tx_hash = tx_hash_

    def create_tumblr_caption(self):
        self.tumblr_caption = '{} bought for Ξ{} (${})\n'.format(self.name, self.eth_nft_price, self.total_usd_cost)
        if self.num_of_assets > 1:
            self.tumblr_caption = '{}\n{} assets bought for Ξ{} (${})\n'.\
                format(self.name, self.num_of_assets, self.eth_nft_price, self.total_usd_cost)
        self.tumblr_caption += '\n\n' + self.link + '\n\n'


class _PostFromOpenSeaTumblr:  # class which holds all operations and utilizes both OpenSea API and Tumblr API
    def __init__(self, address, supply, values_file):  # initialize all the fields
        tumblr_values_file = values_file
        values = open(tumblr_values_file, 'r')
        self.tags = values.readline().strip().split()
        self.tumblr_tags = [tag for tag in self.tags]
        self.collection_name = values.readline().strip()
        tumblr_consumer_key = values.readline().strip()
        tumblr_consumer_secret = values.readline().strip()
        tumblr_oauth_token = values.readline().strip()
        tumblr_oauth_token_secret = values.readline().strip()
        self.os_api_key = values.readline().strip()
        self.blog_name = values.readline().strip()
        values.close()
        self.file_name = self.collection_name + '_tumblr.jpeg'
        self.contract_address = address
        self.total_supply = supply
        self.os_events_url = 'https://api.opensea.io/api/v1/events/'
        self.os_asset_url = 'https://api.opensea.io/api/v1/asset/'
        self.ether_scan_api_url = 'https://api.etherscan.io/api'
        self.response = None
        self.os_obj_to_post = None
        self.tx_db = TinyDB(self.collection_name + '_tx_hash_tumblr_db.json')
        self.tx_query = Query()
        self.tx_queue = []
        self.os_limit = 10
        self.ether_scan_limit = int(self.os_limit * 1.5)
        self.tumblr = pytumblr.TumblrRestClient(
            tumblr_consumer_key,
            tumblr_consumer_secret,
            tumblr_oauth_token,
            tumblr_oauth_token_secret
        )
        self.ua = UserAgent()

    def get_recent_sales(self):  # gets {limit} most recent sales
        try:
            query_strings = {
                'asset_contract_address': self.contract_address,
                'event_type': 'successful',
                'only_opensea': 'false',
                'offset': 0,
                'limit': self.os_limit
            }
            headers = CaseInsensitiveDict()
            headers['Accept'] = 'application/json'
            headers['User-Agent'] = self.ua.random
            headers['x-api-key'] = self.os_api_key
            self.response = requests.get(self.os_events_url, headers=headers, params=query_strings, timeout=3)
            return self.response.status_code == 200
        except Exception as e:
            print(e, flush=True)
            return False

    def parse_response_objects(self):  # parses {limit} objects
        if len(self.tx_queue) > 0:
            queue_has_objects = self.process_queue()
            if queue_has_objects:
                return True
        for i in range(0, self.os_limit):
            try:
                try:
                    base = self.response.json()['asset_events'][i]
                except IndexError:
                    continue
                tx_hash = str(base['transaction']['transaction_hash'])
                tx_exists = False if len(self.tx_db.search(self.tx_query.tx == tx_hash)) == 0 else True
                if tx_exists:
                    continue
                if base['asset_bundle'] is not None:
                    bundle = base['asset_bundle']
                    image_url = bundle['asset_contract']['collection']['large_image_url']
                    eth_nft_price = float('{0:.5f}'.format(int(base['total_price']) / 1e18))
                    usd_price = float(base['payment_token']['usd_price'])
                    total_usd_cost = '{:.2f}'.format(round(eth_nft_price * usd_price, 2))
                    link = bundle['permalink']
                    name = bundle['name']
                    num_of_assets = len(bundle['assets'])
                    transaction = _OpenSeaTransactionObject(name, image_url, eth_nft_price, total_usd_cost, link,
                                                            num_of_assets, tx_hash)
                    transaction.create_tumblr_caption()
                    self.tx_queue.append(transaction)
                    continue
                asset = base['asset']
                name = str(asset['name'])
                image_url = asset['image_url']
            except TypeError:
                continue
            try:
                eth_nft_price = float('{0:.5f}'.format(int(base['total_price']) / 1e18))
                usd_price = float(base['payment_token']['usd_price'])
                total_usd_cost = '{:.2f}'.format(round(eth_nft_price * usd_price, 2))
                link = asset['permalink']
            except (ValueError, TypeError):
                continue
            transaction = _OpenSeaTransactionObject(name, image_url, eth_nft_price, total_usd_cost, link, 1, tx_hash)
            transaction.create_tumblr_caption()
            self.tx_queue.append(transaction)
        return self.process_queue()

    def process_queue(self):  # processes the queue thus far
        index = 0
        while index < len(self.tx_queue):
            cur_os_obj = self.tx_queue[index]
            if cur_os_obj.is_posted:
                self.tx_queue.pop(index)
            else:
                index += 1
        if len(self.tx_queue) == 0:
            return False
        self.os_obj_to_post = self.tx_queue[-1]
        return True

    def post_to_tumblr(self):  # uploads to Tumblr
        try:
            if self.os_obj_to_post.image_url is None:
                self.tumblr.create_text(self.blog_name, state='published', tags=self.tumblr_tags,
                                        body=self.os_obj_to_post.tumblr_caption)
                self.os_obj_to_post.is_posted = True
                self.tx_db.insert({'tx': self.os_obj_to_post.tx_hash})
                return True
            self.tumblr.create_photo(self.blog_name, state='published', tags=self.tumblr_tags,
                                     source=self.os_obj_to_post.image_url, caption=self.os_obj_to_post.tumblr_caption)
            self.os_obj_to_post.is_posted = True
            self.tx_db.insert({'tx': self.os_obj_to_post.tx_hash})
            return True
        except Exception as e:
            print(e, flush=True)
            return False


class ManageFlowObj:  # Main class which does all of the operations
    def __init__(self, tumblr_values_file):
        self.tumblr_values_file = tumblr_values_file
        collection_stats = self.validate_params()
        cont_address = collection_stats[0]
        supply = collection_stats[1]
        self.__base_obj = _PostFromOpenSeaTumblr(cont_address, supply, self.tumblr_values_file)
        self._begin()

    def validate_params(self):
        print('Beginning validation of Tumblr Values File...')
        if not str(self.tumblr_values_file).lower().endswith('.txt'):
            raise Exception('Tumblr Values must be a .txt file.')
        with open(self.tumblr_values_file) as values_file:
            if len(values_file.readlines()) != 8:
                raise Exception('The Tumblr Values file must be formatted correctly.')
        print('Number of lines validated.')
        values_file_test = open(self.tumblr_values_file, 'r')
        hashtags_test = values_file_test.readline().strip()
        hashtags = 0
        words_in_hash_tag = hashtags_test.split()
        if hashtags_test != 'None':
            if len(hashtags_test) == 0 or hashtags_test.split() == 0:
                values_file_test.close()
                raise Exception('Hashtags field is empty.')
            if len(hashtags_test) >= 120:
                values_file_test.close()
                raise Exception('Too many characters in hashtags.')
            if len(words_in_hash_tag) > 10:
                values_file_test.close()
                raise Exception('Too many hashtags.')
            for word in words_in_hash_tag:
                if word[0] == '#':
                    hashtags += 1
            if hashtags != len(words_in_hash_tag):
                values_file_test.close()
                raise Exception('All words must be preceded by a hashtag (#).')
        print('Hashtags validated...')
        collection_name_test = values_file_test.readline().strip()
        test_collection_name_url = 'https://api.opensea.io/api/v1/collection/{}'.format(collection_name_test)
        test_response = requests.get(test_collection_name_url)
        if test_response.status_code == 200:
            collection_json = test_response.json()['collection']
            stats_json = collection_json['stats']
            total_supply = int(stats_json['total_supply'])
            primary_asset_contracts_json = collection_json['primary_asset_contracts'][0]  # got the contract address
            contract_address = primary_asset_contracts_json['address']
        else:
            values_file_test.close()
            raise Exception('The provided collection name does not exist.')
        print('Collection validated...')
        consumer_key = values_file_test.readline().strip()
        consumer_secret = values_file_test.readline().strip()
        oauth_token = values_file_test.readline().strip()
        oauth_secret = values_file_test.readline().strip()
        tumblr_test = pytumblr.TumblrRestClient(
            consumer_key,
            consumer_secret,
            oauth_token,
            oauth_secret
        )
        try:
            _ = tumblr_test.info()['user']['name']
        except KeyError:
            values_file_test.close()
            raise Exception('Invalid Tumblr Keys supplied.')
        print('Tumblr credentials validated...')
        test_os_key = values_file_test.readline().strip()
        test_os_key_url = 'https://api.opensea.io/api/v1/events?only_opensea=false&offset=0&limit=1'
        test_os_headers = CaseInsensitiveDict()
        test_os_headers['Accept'] = 'application/json'
        test_os_headers['x-api-key'] = test_os_key
        test_os_response = requests.get(test_os_key_url, headers=test_os_headers)
        if test_os_response.status_code != 200:
            values_file_test.close()
            raise Exception('Invalid OpenSea API key supplied.')
        print('OpenSea Key validated...')
        print('Validation of Tumblr Values .txt complete. No errors found...')
        print('All files are validated. Beginning program...')
        return [contract_address, total_supply]

    def run_methods(self, date_time_now):  # runs all the methods
        self.check_os_api_status(date_time_now)

    def check_os_api_status(self, date_time_now):
        os_api_working = self.__base_obj.get_recent_sales()
        if os_api_working:
            self.check_if_new_post_exists(date_time_now)
        else:
            print('OS API is not working at roughly', date_time_now, flush=True)
            time.sleep(30)

    def check_if_new_post_exists(self, date_time_now):
        new_post_exists = self.__base_obj.parse_response_objects()
        if new_post_exists:
            self.try_to_post_to_tumblr(date_time_now)
        else:
            print('No new post at roughly', date_time_now, flush=True)
            time.sleep(5)

    def try_to_post_to_tumblr(self, date_time_now):
        posted_to_tumblr = self.__base_obj.post_to_tumblr()
        if posted_to_tumblr:
            print('Posted to Tumblr at roughly', date_time_now, flush=True)
            time.sleep(5)
        else:
            print('Post to Tumblr error at roughly', date_time_now, flush=True)
            time.sleep(15)

    def _begin(self):  # begin program!
        while True:
            date_time_now = datetime.datetime.fromtimestamp(time.time()).strftime('%m/%d/%Y %H:%M:%S')
            self.run_methods(date_time_now)
