#!/usr/bin/env python3
import urllib.request
import tarfile
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
out_dir = ROOT / "reports" / "ablations" / "phase8-bio-dpo-eval-fast-p12-t0p8-s7"
out_dir.mkdir(parents=True, exist_ok=True)

# Step 9 sequence to graft as the query
seq_step9 = "MVSKLFTQSVSSSGTTLSAAAVATVTSAYPLTTSPVGVKLLAGQSLVDAGYTVDAGFGTAAGPYAPGTNGDWYYCFSSKSWADDCDLPLVPPALPSGAALGTSGDASGINPTAALILAAGLEAVRTLSDRPFNVQSYAANASAVAGLTTSSTTTAYDAAGGRAIYGPAGSSDLTVFGESAGGQASQFVNQAVAGAADPNSRCGQCSAIGNTGESPILSTYASHGLLVNNHVIGWTDWNLALDQLGQMATYDCSDKQHPSVAGLGYDDPNFNGEDTAVSNFAVTAAALVVNASELGQAKANPTAQGILAAGVPAGAAYPVLLLSAG"

def graft_msa():
    ticket_id = "4CyjY-DHHFo80i1ojK9fLqsYfT3nXrHg0glZEg"
    url = f"https://api.colabfold.com/result/download/{ticket_id}"
    print(f"Downloading natural MSA from {url}...")
    
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read()
            
            # Extract the uniref.a3m file from tarball
            tar = tarfile.open(fileobj=io.BytesIO(content), mode="r:gz")
            uniref_file = tar.extractfile("uniref.a3m")
            if not uniref_file:
                print("Error: Could not find uniref.a3m inside the downloaded tarball.")
                return
                
            a3m_text = uniref_file.read().decode("utf-8")
            lines = a3m_text.splitlines()
            
            # Graft the Step 9 sequence in place of the natural query
            # A3M format structure:
            # Line 1: >query
            # Line 2: natural sequence (to be replaced)
            # Lines 3+: all the homologous sequences
            if lines[0] == ">query":
                lines[1] = seq_step9
            else:
                print("Warning: First line is not >query, attempting custom grafting...")
                # Fallback: find first line starting with >query and replace the next line
                for idx, line in enumerate(lines):
                    if line.startswith(">query"):
                        lines[idx+1] = seq_step9
                        break
            
            grafted_text = "\n".join(lines) + "\n"
            out_file = out_dir / "DPO_Candidate_Step9_grafted.a3m"
            out_file.write_text(grafted_text, encoding="utf-8")
            
            print(f"\nSUCCESS!")
            print(f"Grafted MSA successfully written to: {out_file}")
            print("You can now download this file and upload it directly to ColabFold.")
            
    except Exception as e:
        print("Error during grafting:", e)

if __name__ == "__main__":
    graft_msa()
