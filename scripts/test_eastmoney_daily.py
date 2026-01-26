from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from gpbt.providers.eastmoney_curl_provider import EastMoneyCurlProvider

def main():
    p = EastMoneyCurlProvider()
    df = p.get_daily_bar('600000.SH','20230101','20230110','qfq')
    print('rows', len(df))
    print(df.head(5))

if __name__ == '__main__':
    main()

