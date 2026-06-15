import re
import json

def clean_raw_text_stepwise(val, is_html=False):
    if not val:
        return val
    
    print("--- STEP 0: Original Length:", len(val))
    
    competitor_domains_simple = [
        'freshershunt', 'freshersvoice', 'jobsarkari', 'sarkariresult', 
        'careerbywell', 'sarkarijob', 'freejobalert', 'indgovtjobs', 'govtjobsalert'
    ]
    
    if is_html:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(val, "html.parser")
        
        # 1. Handle all anchor tags first
        for a in soup.find_all("a"):
            href = a.get("href", "")
            if any(comp in href.lower() for comp in competitor_domains_simple):
                a.unwrap()
            elif not href:
                a.unwrap()
                
        # 2. Recursively clean text nodes
        for text_node in soup.find_all(text=True):
            if not text_node.string:
                continue
            if text_node.parent and text_node.parent.name in ['script', 'style']:
                continue
                
            txt = text_node.string
            
            # Remove competitor URLs inside text nodes
            for comp in competitor_domains_simple:
                txt = re.sub(r'(?i)https?://\S*' + comp + r'\S*', '', txt)
                txt = re.sub(r'(?i)\b\S*' + comp + r'\S*', '', txt)
                
            txt = re.sub(r'(?i)https?://\.in/\S*', '', txt)
            txt = re.sub(r'(?i)https?://\.in\b', '', txt)
            
            # Phrases
            phrases_to_remove = [
                r'(?i)\bvisit\s+the\s+full\s+details\s+and\s+application\s+page\b',
                r'(?i)\bfollow\s+the\s+instructions\s+provided\s+on\s+the\s+page\s+to\s+complete\s+your\s+application\b',
                r'(?i)\bfor\s+a\s+detailed\s+guide\s+on\s+the\s+application\s+process\s*,\s*refer\s+to\s+the\s+youtube\s+video\b',
                r'(?i)\bclick\s+here\s+to\s+apply\b',
                r'(?i)\bofficial\s+website\b',
                r'(?i)\bofficial\s+notification\b',
                r'(?i)\bapply\s+online\b'
            ]
            for phrase in phrases_to_remove:
                txt = re.sub(phrase, '', txt)
                
            # Names
            for name in competitor_domains_simple:
                txt = re.sub(r'(?i)\b' + name + r'\b', '', txt)
                
            # Numbered lists stripping
            txt = re.sub(r'\b\d+\.\s*(?:\.|:|-)*\s+', '', txt)
            
            # Cleanup multiple spacing/punctuation
            txt = re.sub(r'\s+', ' ', txt)
            txt = re.sub(r'\.\s*\.+', '.', txt)
            txt = re.sub(r'-\s*-+', '-', txt)
            txt = re.sub(r':\s*:+', ':', txt)
            txt = re.sub(r'\.\s*\.', '.', txt)
            txt = re.sub(r':\s*\.', ':', txt)
            
            if txt != text_node.string:
                text_node.replace_with(txt)
                
        cleaned = str(soup)
        print("--- STEP 6: Final Cleaned Length:", len(cleaned))
        return cleaned
    else:
        # Fallback for plain text
        cleaned = val
        for comp in competitor_domains_simple:
            cleaned = re.sub(r'(?i)https?://\S*' + comp + r'\S*', '', cleaned)
            cleaned = re.sub(r'(?i)\b\S*' + comp + r'\S*', '', cleaned)
            
        cleaned = re.sub(r'(?i)https?://\.in/\S*', '', cleaned)
        cleaned = re.sub(r'(?i)https?://\.in\b', '', cleaned)
        
        phrases_to_remove = [
            r'(?i)\bvisit\s+the\s+full\s+details\s+and\s+application\s+page\b',
            r'(?i)\bfollow\s+the\s+instructions\s+provided\s+on\s+the\s+page\s+to\s+complete\s+your\s+application\b',
            r'(?i)\bfor\s+a\s+detailed\s+guide\s+on\s+the\s+application\s+process\s*,\s*refer\s+to\s+the\s+youtube\s+video\b',
            r'(?i)\bclick\s+here\s+to\s+apply\b',
            r'(?i)\bofficial\s+website\b',
            r'(?i)\bofficial\s+notification\b',
            r'(?i)\bapply\s+online\b'
        ]
        for phrase in phrases_to_remove:
            cleaned = re.sub(phrase, '', cleaned)
            
        for name in competitor_domains_simple:
            cleaned = re.sub(r'(?i)\b' + name + r'\b', '', cleaned)
            
        cleaned = re.sub(r'\b\d+\.\s*(?:\.|:|-)*\s+', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        cleaned = re.sub(r'\.\s*\.+', '.', cleaned)
        cleaned = re.sub(r'-\s*-+', '-', cleaned)
        cleaned = re.sub(r':\s*:+', ':', cleaned)
        cleaned = re.sub(r'\.\s*\.', '.', cleaned)
        cleaned = re.sub(r':\s*\.', ':', cleaned)
        
        strip_chars = " -|:_!@#%^&*()[]{}<>.,/\\\"'"
        cleaned = cleaned.strip(strip_chars)
        cleaned = re.sub(r'(?i)\s+\b(at|on|visit|from|link|website|official)\b\s*$', '', cleaned)
        cleaned = cleaned.strip(strip_chars)
        print("--- STEP 6: Final Cleaned Length:", len(cleaned))
        return cleaned

def main():
    with open("queue_job_11.json", "r", encoding="utf-8") as f:
        job = json.load(f)
        
    desc = job.get("jobDescription", "")
    
    cleaned_desc = clean_raw_text_stepwise(desc, is_html=True)
    
    # Save the output of the test
    with open("test_cleaned_desc.html", "w", encoding="utf-8") as f:
        f.write(cleaned_desc)
        
    print("\n--- Compare excerpts ---")
    print("Original excerpt around government jobs:")
    idx = desc.find("government jobs</a>")
    if idx != -1:
        print(desc[idx-100 : idx+300])
    else:
        print("Not found in original")
        
    print("\nCleaned excerpt around government jobs:")
    idx2 = cleaned_desc.find("government jobs")
    if idx2 != -1:
        print(cleaned_desc[idx2-100 : idx2+300])
    else:
        # Let's print from index 1000 to 1500 of cleaned
        print("Not found in cleaned, printing chunk:")
        print(cleaned_desc[1000:1500])

if __name__ == "__main__":
    main()
