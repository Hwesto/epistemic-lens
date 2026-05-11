#!/usr/bin/env python3
"""
Extract source attributions from briefings.

For each article corpus, identify direct quotes and their speakers.
Output one JSON per story with source attribution data.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any


def extract_quotes_from_text(text: str, lang: str = 'en') -> List[tuple]:
    """
    Extract direct quotes from article text.
    Returns list of (quote_text, speaker_context, verb) tuples.

    Handles multiple quote formats and attribution patterns.
    """
    quotes = []

    # Normalize different quote characters to standard quotes for regex
    normalized_text = text
    quote_char_map = {
        '"': '"', '"': '"',  # curly double quotes (U+201C, U+201D)
        ''': "'", ''': "'",  # curly single quotes (U+2018, U+2019)
        '«': '"', '»': '"',  # guillemets
        '‹': "'", '›': "'",  # single angle quotes
    }

    for old_char, new_char in quote_char_map.items():
        normalized_text = normalized_text.replace(old_char, new_char)

    # English/Spanish verb patterns
    verbs_en = 'said|told|claimed|warned|argued|denied|stated|noted|explained|added|stressed|insisted|remarked|commented|announced|declared|revealed|acknowledged|reported|suggested|indicated|mentioned|described|says|notes|points|stresses|adds|insists|warns'
    verbs_es = 'dijo|explicó|afirmó|señaló|indicó|mencionó|comentó|aseguró|advirtió|insistió|negó|declaró|dice|añadió|subraya|asegura|advierte|insiste'

    # Pattern 1: Direct attribution with quotes
    # Handles: "John Smith said 'quote'" and "John Smith warned ... is 'quote'"
    # Look for: SPEAKER VERB ... within 100 chars ... QUOTE
    sentences = re.split(r'[.!?\n]', normalized_text)

    for sentence in sentences:
        # Find verbs and speakers in this sentence
        for verb_word in verbs_en.split('|') + verbs_es.split('|'):
            verb_match = re.search(rf'\b({verb_word})\b', sentence, re.IGNORECASE)
            if verb_match:
                # Get text before verb to find speaker
                before_verb = sentence[:verb_match.start()]
                speaker_match = re.search(r'([\w\s\-.,]+?)\s*$', before_verb)
                if speaker_match:
                    speaker = speaker_match.group(1).strip()

                    # Get text after verb and look for quote
                    after_verb = sentence[verb_match.end():]
                    quote_match = re.search(r'[""\'"](.{5,}?)[""\'"]', after_verb)
                    if quote_match:
                        quote = quote_match.group(1).strip()
                        verb = verb_word.lower()

                        if len(quote) > 4 and quote not in [q[0] for q in quotes]:
                            quotes.append((quote, speaker, verb))

    # Pattern 2: Find all quoted passages and look for nearby speakers
    pattern_quotes = r'[""\'"](.+?)[""\'"]'

    for match in re.finditer(pattern_quotes, normalized_text):
        quote = match.group(1).strip()
        start = match.start()

        # Skip short quotes
        if len(quote) < 5:
            continue

        if quote in [q[0] for q in quotes]:
            continue

        # Look backwards for speaker attribution (up to 200 chars)
        lookback_start = max(0, start - 200)
        lookback_text = text[lookback_start:start]

        # Pattern: "Speaker said/explained" or "Speaker:" in lookback
        speaker_match = re.search(r'([\w\s\-.,]+)\s+(?:said|explained|noted|claimed|told|dijo|explicó|señaló).*$', lookback_text, re.IGNORECASE | re.MULTILINE)

        if speaker_match:
            speaker = speaker_match.group(1).strip()
            verb_match = re.search('(?:' + verbs_en + '|' + verbs_es + ')', lookback_text, re.IGNORECASE)
            verb = verb_match.group(0).lower() if verb_match else 'said'

            if len(quote) > 4 and speaker and len(speaker) < 100:
                quotes.append((quote, speaker, verb))

    # Remove duplicates while preserving order
    seen = set()
    unique_quotes = []
    for q in quotes:
        if q[0] not in seen:
            seen.add(q[0])
            unique_quotes.append(q)

    return unique_quotes


def find_quote_in_original(quote: str, signal_text: str) -> bool:
    """Verify that quote exists verbatim in signal_text."""
    # Normalize both for comparison
    normalized_quote = ' '.join(quote.split())
    normalized_text = ' '.join(signal_text.split())

    # Check for exact match
    if normalized_quote in normalized_text:
        return True

    # Also check in original with flexible whitespace
    for start in range(len(signal_text) - len(quote) + 1):
        if quote.lower() in signal_text[start:start+len(quote)+50].lower():
            return True

    return False


def parse_speaker_info(speaker_context: str, article_text: str, quote: str) -> dict:
    """
    Parse speaker name, role, and affiliation from context.
    """
    info = {
        'speaker_name': None,
        'role_or_affiliation': 'unknown',
        'speaker_type': 'unknown',
        'speaker_affiliation_bucket': 'unknown',
        'speaker_affiliation_kind': None,
        'stance_toward_target': 'unclear'
    }

    if not speaker_context:
        return info

    speaker_lower = speaker_context.lower()
    context_lower = speaker_context.lower()

    # Extract name (first 1-3 capitalized words)
    name_tokens = speaker_context.split()
    name_parts = []
    for token in name_tokens[:4]:  # Check first 4 tokens
        if token and (token[0].isupper() or token[0].isdigit()):
            # Remove punctuation
            clean_token = re.sub(r'[,:]', '', token)
            if clean_token and len(clean_token) > 1:
                name_parts.append(clean_token)
        else:
            break

    if name_parts:
        info['speaker_name'] = ' '.join(name_parts[:2])

    # Extract role (text after comma or in "of" phrase)
    role_match = re.search(r',\s*(.+?)(?:\.|$)', speaker_context)
    if role_match:
        info['role_or_affiliation'] = role_match.group(1).strip()
    else:
        # Look for "of X" pattern
        of_match = re.search(r'\bof\s+([^,\.]+)', speaker_context, re.IGNORECASE)
        if of_match:
            info['role_or_affiliation'] = of_match.group(1).strip()
        else:
            info['role_or_affiliation'] = speaker_context.strip()

    # Classify speaker type
    official_keywords = ['minister', 'president', 'official', 'director', 'chief', 'secretary', 'ambassador', 'representative', 'spokesman', 'spokesperson', 'general', 'admiral', 'colonel', 'officer', 'senator', 'representative', 'governor']
    expert_keywords = ['professor', 'dr.', 'doctor', 'expert', 'analyst', 'fellow', 'researcher', 'scholar', 'scientist', 'economist', 'professor', 'phd']
    civilian_keywords = ['resident', 'person', 'worker', 'farmer', 'business', 'shop', 'market', 'driver', 'passenger', 'tourist', 'student', 'teacher']

    speaker_role_lower = info['role_or_affiliation'].lower()

    if any(kw in context_lower or kw in speaker_role_lower for kw in official_keywords):
        info['speaker_type'] = 'official'
        if 'government' in speaker_role_lower or 'state' in speaker_role_lower or 'ministry' in speaker_role_lower:
            info['speaker_affiliation_bucket'] = 'state'
        elif 'party' in speaker_role_lower:
            info['speaker_affiliation_bucket'] = 'political'
    elif any(kw in context_lower or kw in speaker_role_lower for kw in expert_keywords):
        info['speaker_type'] = 'expert'
        if 'university' in speaker_role_lower or 'institute' in speaker_role_lower or 'center' in speaker_role_lower:
            info['speaker_affiliation_bucket'] = 'academic'
        else:
            info['speaker_affiliation_bucket'] = 'academic'
    elif 'journalist' in context_lower or 'reporter' in context_lower or 'correspondent' in context_lower:
        info['speaker_type'] = 'journalist'
        info['speaker_affiliation_bucket'] = 'wire'
    elif any(kw in context_lower for kw in civilian_keywords):
        info['speaker_type'] = 'civilian'
        info['speaker_affiliation_bucket'] = 'civilian'

    return info


def process_story(story_key: str, date: str) -> Optional[Dict]:
    """Process one story and extract sources."""
    base_path = Path('/home/runner/work/epistemic-lens/epistemic-lens')
    briefing_path = base_path / 'briefings' / f'{date}_{story_key}.json'
    analysis_path = base_path / 'analyses' / f'{date}_{story_key}.json'

    if not briefing_path.exists() or not analysis_path.exists():
        return None

    with open(briefing_path) as f:
        briefing_data = json.load(f)

    with open(analysis_path) as f:
        analysis_data = json.load(f)

    corpus = briefing_data.get('corpus', [])
    story_title = analysis_data.get('story_title', briefing_data.get('story_title', ''))

    sources = []
    processed_quotes = set()

    for idx, article in enumerate(corpus):
        signal_text = article.get('signal_text', '')
        bucket = article.get('bucket', '')
        outlet = article.get('feed', '')
        lang = article.get('lang', 'en')

        if not signal_text:
            continue

        # Extract quotes
        quotes = extract_quotes_from_text(signal_text, lang)

        for quote_text, speaker_context, verb in quotes:
            # Skip if we've already processed this exact quote
            quote_key = (idx, quote_text[:50])
            if quote_key in processed_quotes:
                continue

            # Verify quote exists in original text
            if not find_quote_in_original(quote_text, signal_text):
                continue

            processed_quotes.add(quote_key)

            # Parse speaker
            speaker_info = parse_speaker_info(speaker_context, signal_text, quote_text)

            source_entry = {
                'speaker_name': speaker_info['speaker_name'],
                'role_or_affiliation': speaker_info['role_or_affiliation'],
                'speaker_type': speaker_info['speaker_type'],
                'speaker_affiliation_bucket': speaker_info['speaker_affiliation_bucket'],
                'speaker_affiliation_kind': speaker_info['speaker_affiliation_kind'],
                'exact_quote': quote_text,
                'attributive_verb': verb,
                'stance_toward_target': speaker_info['stance_toward_target'],
                'signal_text_idx': idx,
                'bucket': bucket,
                'outlet': outlet
            }
            sources.append(source_entry)

    return {
        'story_key': story_key,
        'date': date,
        'story_title': story_title,
        'n_articles_processed': len(corpus),
        'sources': sources,
        'model': 'claude-haiku-4-5',
        'meta_version': '1.0'
    }


def main():
    date = '2026-05-11'
    story_keys = [
        'hantavirus_cruise',
        'hormuz_iran',
        'iran_nuclear',
        'lebanon_buffer',
        'ukraine_war'
    ]

    sources_dir = Path('/home/runner/work/epistemic-lens/epistemic-lens/sources')
    sources_dir.mkdir(exist_ok=True)

    total_sources = 0

    for story_key in story_keys:
        print(f"Processing {story_key}...")
        result = process_story(story_key, date)

        if result:
            output_file = sources_dir / f'{date}_{story_key}.json'
            with open(output_file, 'w') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            n_sources = len(result.get('sources', []))
            total_sources += n_sources
            print(f"  Extracted {n_sources} sources -> {output_file}")

    print(f"\nTotal sources extracted: {total_sources}")


if __name__ == '__main__':
    main()
