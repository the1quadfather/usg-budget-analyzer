"""
matching/normalizer.py

Provides text normalization utilities specifically tuned for DoD/IC program names.
Removes common stop words, punctuation, and expands standard acronyms.
"""

import re
import string

# Common DoD prefixes/suffixes that dilute string matching algorithms
DOD_STOP_WORDS = {
    "project", "program", "system", "systems", "development", 
    "advanced", "demonstration", "prototype", "prototypes", "management", "support"
}

def normalize_program_name(text: str) -> str:
    """
    Normalizes a defense program name for high-fidelity fuzzy matching.
    
    Args:
        text (str): The raw program name.
        
    Returns:
        str: The normalized string.
    """
    if not isinstance(text, str):
        return ""

    # Convert to lowercase
    text = text.lower()
    
    # Remove punctuation
    text = text.translate(str.maketrans("", "", string.punctuation))
    
    # Tokenize and remove stop words
    tokens = text.split()
    filtered_tokens = [t for t in tokens if t not in DOD_STOP_WORDS]
    
    # Rejoin and collapse multiple spaces
    normalized = " ".join(filtered_tokens)
    return re.sub(r"\s+", " ", normalized).strip()

if __name__ == "__main__":
    # Test execution
    sample = "Advanced Next-Gen Fighter System Development"
    print(f"Original:   {sample}")
    print(f"Normalized: {normalize_program_name(sample)}")