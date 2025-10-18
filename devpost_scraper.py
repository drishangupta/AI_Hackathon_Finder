#!/usr/bin/env python3
"""
Devpost Hackathon Scraper
Scrapes hackathon listings from devpost.com/hackathons
"""

import requests
import json
import time
from datetime import datetime
from bs4 import BeautifulSoup
import re

class DevpostScraper:
    def __init__(self):
        self.base_url = "https://devpost.com"
        self.api_url = "https://devpost.com/api/hackathons"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://devpost.com/hackathons',
            'Origin': 'https://devpost.com'
        })
    
    def get_hackathons_from_api(self, page=1, per_page=50):
        """Fetch hackathons from Devpost API"""
        try:
            params = {
                'page': page,
                'per_page': per_page,
                'challenge_type': 'all',
                'order': 'submission_deadline',
                'sort': 'ascending'
            }
            
            response = self.session.get(self.api_url, params=params)
            response.raise_for_status()
            
            return response.json()
        except Exception as e:
            print(f"Error fetching from API: {e}")
            return None
    
    def get_featured_hackathons(self):
        """Fetch featured hackathons"""
        try:
            url = "https://devpost.com/api/hackathons/featured_hackathons"
            response = self.session.get(url)
            response.raise_for_status()
            
            return response.json()
        except Exception as e:
            print(f"Error fetching featured hackathons: {e}")
            return None
    
    def scrape_hackathon_details(self, hackathon_url):
        """Scrape detailed information from individual hackathon page"""
        try:
            if not hackathon_url.startswith('http'):
                hackathon_url = self.base_url + hackathon_url
            
            response = self.session.get(hackathon_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            details = {}
            
            # Extract title
            title_elem = soup.find('h1', class_='challenge-title')
            if title_elem:
                details['title'] = title_elem.get_text(strip=True)
            
            # Extract description
            desc_elem = soup.find('div', class_='challenge-description')
            if desc_elem:
                details['description'] = desc_elem.get_text(strip=True)
            
            # Extract prizes
            prize_elems = soup.find_all('div', class_='prize-amount')
            if prize_elems:
                details['prizes'] = [elem.get_text(strip=True) for elem in prize_elems]
            
            # Extract dates
            date_elems = soup.find_all('time')
            dates = {}
            for elem in date_elems:
                if 'datetime' in elem.attrs:
                    parent = elem.find_parent()
                    if parent:
                        label = parent.get_text(strip=True).lower()
                        if 'submission' in label or 'deadline' in label:
                            dates['submission_deadline'] = elem['datetime']
                        elif 'start' in label:
                            dates['start_date'] = elem['datetime']
            
            details['dates'] = dates
            
            return details
            
        except Exception as e:
            print(f"Error scraping hackathon details from {hackathon_url}: {e}")
            return {}
    
    def parse_hackathon_data(self, hackathon_data):
        """Parse and normalize hackathon data"""
        parsed = {
            'id': hackathon_data.get('id'),
            'title': hackathon_data.get('title', '').strip(),
            'url': hackathon_data.get('url', ''),
            'thumbnail_url': hackathon_data.get('thumbnail_url', ''),
            'submission_period_dates': hackathon_data.get('submission_period_dates', ''),
            'themes': hackathon_data.get('themes', []),
            'prize_amount': hackathon_data.get('prize_amount', ''),
            'registrations_count': hackathon_data.get('registrations_count', 0),
            'organization_name': hackathon_data.get('organization_name', ''),
            'featured': hackathon_data.get('featured', False),
            'status': 'upcoming' if 'upcoming' in hackathon_data.get('submission_period_dates', '').lower() else 'active',
            'scraped_at': datetime.now().isoformat()
        }
        
        # Parse dates if available
        if hackathon_data.get('submission_period_dates'):
            parsed['submission_period'] = hackathon_data['submission_period_dates']
        
        return parsed
    
    def scrape_all_hackathons(self):
        """Scrape all available hackathons"""
        all_hackathons = []
        
        print("Fetching featured hackathons...")
        featured_data = self.get_featured_hackathons()
        if featured_data and 'hackathons' in featured_data:
            for hackathon in featured_data['hackathons']:
                parsed = self.parse_hackathon_data(hackathon)
                parsed['featured'] = True
                all_hackathons.append(parsed)
                print(f"  Found featured: {parsed['title']}")
        
        print("\nFetching regular hackathons...")
        page = 1
        while True:
            data = self.get_hackathons_from_api(page=page)
            if not data or 'hackathons' not in data:
                break
            
            hackathons = data['hackathons']
            if not hackathons:
                break
            
            for hackathon in hackathons:
                parsed = self.parse_hackathon_data(hackathon)
                # Avoid duplicates from featured hackathons
                if not any(h['id'] == parsed['id'] for h in all_hackathons):
                    all_hackathons.append(parsed)
                    print(f"  Found: {parsed['title']}")
            
            page += 1
            time.sleep(1)  # Be respectful to the server
            
            # Safety check - don't go beyond reasonable pages
            if page > 10:
                break
        
        return all_hackathons
    
    def save_to_json(self, hackathons, filename='devpost_hackathons.json'):
        """Save hackathons to JSON file"""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump({
                    'source': 'devpost.com',
                    'scraped_at': datetime.now().isoformat(),
                    'total_count': len(hackathons),
                    'hackathons': hackathons
                }, f, indent=2, ensure_ascii=False)
            print(f"\nSaved {len(hackathons)} hackathons to {filename}")
        except Exception as e:
            print(f"Error saving to JSON: {e}")

def main():
    """Main scraping function"""
    print("Starting Devpost hackathon scraper...")
    
    scraper = DevpostScraper()
    hackathons = scraper.scrape_all_hackathons()
    
    if hackathons:
        scraper.save_to_json(hackathons)
        
        # Print summary
        print(f"\n=== SCRAPING SUMMARY ===")
        print(f"Total hackathons found: {len(hackathons)}")
        
        featured_count = sum(1 for h in hackathons if h.get('featured'))
        print(f"Featured hackathons: {featured_count}")
        
        active_count = sum(1 for h in hackathons if h.get('status') == 'active')
        upcoming_count = sum(1 for h in hackathons if h.get('status') == 'upcoming')
        print(f"Active hackathons: {active_count}")
        print(f"Upcoming hackathons: {upcoming_count}")
        
        # Show sample hackathons
        print(f"\n=== SAMPLE HACKATHONS ===")
        for i, hackathon in enumerate(hackathons[:5]):
            print(f"{i+1}. {hackathon['title']}")
            print(f"   Organization: {hackathon['organization_name']}")
            print(f"   Dates: {hackathon['submission_period_dates']}")
            print(f"   Registrations: {hackathon['registrations_count']}")
            print(f"   URL: {hackathon['url']}")
            print()
        
        return hackathons
    else:
        print("No hackathons found!")
        return []

if __name__ == "__main__":
    hackathons = main()