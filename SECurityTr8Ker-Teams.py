import os
import requests
import xmltodict
import logging
import colorlog
from bs4 import BeautifulSoup
import time
from datetime import datetime
import re
import json

# Define request interval, log file path, and logs directory
REQUEST_INTERVAL = 0.3
logs_dir = 'logs-teams'
log_file_path = os.path.join(logs_dir, 'debug.log')
teams_disclosures_file = os.path.join(logs_dir, 'teams_disclosures.json')

# Ensure the logs directory exists
if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)

# Initialize the root logger to capture DEBUG level logs
logger = colorlog.getLogger()
logger.setLevel(logging.DEBUG)  # Capture everything at DEBUG level and above

# Setting up colored logging for terminal
terminal_handler = colorlog.StreamHandler()
terminal_handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s%(asctime)s - %(levelname)s - %(message)s',
    log_colors={
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red,bg_white',
    }))
terminal_handler.setLevel(logging.INFO)  # Terminal to show INFO and above
logger.addHandler(terminal_handler)

# Setting up logging to file to capture DEBUG and above
file_handler = logging.FileHandler(log_file_path)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
file_handler.setLevel(logging.DEBUG)  # File to capture everything at DEBUG level
logger.addHandler(file_handler)

def load_teams_disclosures():
    if os.path.exists(teams_disclosures_file):
        with open(teams_disclosures_file, 'r') as file:
            return json.load(file)
    else:
        return {}

def save_teams_disclosures(disclosures):
    with open(teams_disclosures_file, 'w') as file:
        json.dump(disclosures, file)

# Function to post a message to Microsoft Teams
def post_to_teams(webhook_url, company_name, ticker_symbol, document_link, pubDate):
    message = {
        "@context": "http://schema.org/extensions",
        "@type": "MessageCard",
        "themeColor": "0076D7",
        "title": "Material Cybersecurity Incident Detected",
        "text": f"A Material Cybersecurity Incident has been disclosed by {company_name} (Ticker: {ticker_symbol}), published on {pubDate}.",
        "potentialAction": [{
            "@type": "OpenUri",
            "name": "View SEC Filing",
            "targets": [{"os": "default", "uri": document_link}]
        }]
    }
    headers = {'Content-Type': 'application/json'}
    response = requests.post(webhook_url, json=message, headers=headers)
    if response.status_code != 200:
        logger.error(f"Failed to post to Teams: {response.text}")

def get_ticker_symbol(cik_number, company_name):
    url = f"https://data.sec.gov/submissions/CIK{cik_number}.json"
    headers = {'User-Agent': 'Toyota Motor North America/1.0 (cfc.cti@toyota.com)'}
    try:
        response = requests.get(url, headers=headers)
        time.sleep(REQUEST_INTERVAL)
        if response.status_code == 200:
            data = response.json()
            ticker_symbol = data.get('tickers', [])[0] if data.get('tickers') else None
            return ticker_symbol
        else:
            logger.error(f"Error fetching ticker symbol for CIK: {cik_number}")
            return None
    except Exception as e:
        logger.error(f"Error retrieving ticker symbol: {e}")
        return None

def inspect_document_for_cybersecurity(link):
    headers = {'User-Agent': 'Toyota Motor North America/1.0 (cfc.cti@toyota.com)'}
    # Define a list of search terms you're interested in
    search_terms = ["Material Cybersecurity Incidents", "Item 1.05"]
    try:
        response = requests.get(link, headers=headers)
        time.sleep(REQUEST_INTERVAL)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            document_text = soup.get_text()  # Keep the document text as is, respecting case
            # Check if any of the search terms is in the document_text using regex for exact match
            for term in search_terms:
                # Create a regex pattern with word boundaries for the exact term
                pattern = r'\b\s*' + re.escape(term) + r'\s*\b'
                if re.search(pattern, document_text):
                    return True
    except Exception as e:
        logger.error(f"Failed to inspect document at {link}: {e}")
    return False

def fetch_filings_from_rss(url):
    # Teams webhook URL - replace with your actual webhook URL
    teams_webhook_url = "YOUR-TEAMS-TEAM-WEBHOOK-URL"
    teams_disclosures = load_teams_disclosures()  # Load previously posted disclosures

    headers = {'User-Agent': 'Toyota Motor North America/1.0 (cfc.cti@toyota.com)'}
    try:
        response = requests.get(url, headers=headers)
        time.sleep(REQUEST_INTERVAL)
        if response.status_code == 200:
            feed = xmltodict.parse(response.content)
            for item in feed['rss']['channel']['item']:
                xbrlFiling = item['edgar:xbrlFiling']
                form_type = xbrlFiling['edgar:formType']
                pubDate = item['pubDate']
                if form_type in ['8-K', '8-K/A', '6-K', 'FORM 8-K']:
                    company_name = xbrlFiling['edgar:companyName']
                    cik_number = xbrlFiling['edgar:cikNumber']
                    document_links = [xbrlFile['@edgar:url'] for xbrlFile in xbrlFiling['edgar:xbrlFiles']['edgar:xbrlFile'] if xbrlFile['@edgar:url'].endswith(('.htm', '.html'))]
                    
                    for document_link in document_links:
                        if inspect_document_for_cybersecurity(document_link):
                            # Check if this disclosure has already been posted
                            if cik_number not in teams_disclosures:
                                ticker_symbol = get_ticker_symbol(cik_number, company_name)
                                logger.info(f"Cybersecurity Incident Disclosure found: {company_name} (Ticker:${ticker_symbol}) (CIK:{cik_number}) - {document_link} - Published on {pubDate}")
                                # Post to Microsoft Teams
                                post_to_teams(teams_webhook_url, company_name, ticker_symbol, document_link, pubDate)
                                # Update the teams_disclosures to include this disclosure
                                teams_disclosures[cik_number] = datetime.now().isoformat()
                                save_teams_disclosures(teams_disclosures)
                                break  # Assuming we only need to log once per filing
    except Exception as e:
        logger.critical(f"Error fetching filings: {e}", extra={"log_color": "red"})

def monitor_sec_feed():
    rss_url = 'https://www.sec.gov/Archives/edgar/usgaap.rss.xml'
    while True:
        logger.info("Checking SEC RSS feed for 8-K and 6-K filings...")
        fetch_filings_from_rss(rss_url)
        logger.info("Sleeping for 10 minutes before next check...")
        time.sleep(600)  # Sleep for 10 minutes

if __name__ == "__main__":
    monitor_sec_feed()
