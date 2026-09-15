import re
from names_dataset import NameDataset

nd = NameDataset()

country_codes = {
    'England': 'GB', 'Spain': 'ES', 'France': 'FR', 'Germany': 'DE', 
    'Italy': 'IT', 'Portugal': 'PT', 'Brazil': 'BR', 'Argentina': 'AR', 
    'Netherlands': 'NL', 'Nigeria': 'NG', 'Japan': 'JP', 'USA': 'US', 
    'Turkey': 'TR', 'Belgium': 'BE', 'Croatia': 'HR', 'Morocco': 'MA', 
    'Colombia': 'CO', 'Mexico': 'MX', 'South Korea': 'KR', 'Sweden': 'SE'
}

def is_latin(text):
    # Matches standard letters, Latin-1 accents, explicit Turkish characters, hyphens, apostrophes, and spaces
    return bool(re.match(r"^[a-zA-ZÀ-ÿçÇğĞıİöÖşŞüÜ\-\'\s]+$", text))

def expand_names_with_dataset(filepath, name_type):
    with open(filepath, 'r') as f:
        lines = f.readlines()
        
    out_path = f"/Users/cemtarkantekcan/Desktop/packedfootball/packedfootball/data/extended_{name_type}_names.txt"
    
    with open(out_path, 'w') as f:
        for line in lines:
            if ':' not in line:
                f.write(line)
                continue
            
            country, names_str = line.split(":", 1)
            print(f"Processing: {country}")
            
            new_names = set(names_str.strip().split(', '))
            alpha2 = country_codes.get(country, 'US')
            
            if name_type == 'first':
                top_names_dict = nd.get_top_names(n=1000, use_first_names=True, country_alpha2=alpha2, gender='Male')
                pool = top_names_dict.get(alpha2, {}).get('M', [])
            else:
                top_names_dict = nd.get_top_names(n=1000, use_first_names=False, country_alpha2=alpha2)
                pool = top_names_dict.get(alpha2, [])
            
            for name in pool:
                if len(new_names) >= 200:
                    break
                    
                if len(name) <= 11 and is_latin(name):
                    new_names.add(name)
            
            f.write(f"{country}: {', '.join(new_names)}\n")

expand_names_with_dataset("/Users/cemtarkantekcan/Desktop/packedfootball/packedfootball/data/first_names.txt", "first")
expand_names_with_dataset("/Users/cemtarkantekcan/Desktop/packedfootball/packedfootball/data/last_names.txt", "last")