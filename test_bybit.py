# test_bybit.py
from dotenv import load_dotenv
load_dotenv()
from data.bybit_client import BybitClient

client = BybitClient(demo=True)
client.diagnose()