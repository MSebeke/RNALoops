#A simplified and class based approach to motif collection, hopefully making it less of a mess.
#I recommend setting this up as a cronjob for the the 1 first of each month, as the BGSU is somewhat irregularly updated towards the end of each month.
#New fix for duplicate sequences: They will be assigned to the motif they were found with first (order in motifs.json) but with a lower case letter to indicate that they might be something else aswell.
from collections import defaultdict
import json
import os
import re
import requests
from time import sleep
from Bio import AlignIO
from io import StringIO
import sys

class Motif:
    def __init__(self,motif_json:dict):
        self.name = motif_json["motif_name"]
        self.abbreviation = motif_json["abbreviation"]
        self.instances=motif_json["instances"]
        self.loop_type=motif_json["loop_type"]
        self.rfam_ids=motif_json["rfam_id"]
        self.sequence_dict= defaultdict(list,{ key:[] for key in ["bgsu_sequences","bgsu_reverse","rfam_sequences","rfam_reverse"]})

    def reverse_sequences(self,seqlist:list[str]) -> list[str]:
        rev=[]
        for sequence in seqlist:
            reverse=sequence[::-1]
            rev.append(reverse)
        #reverse=[x[::-1] for x in seqlist] #this keeps a reference to the original sequences, leading to extensions added later to be added in the front or even twice sometimes
        return rev
  
    def get_bgsu_sequences(self):
        for instance in self.instances:
            self.sequence_dict["bgsu_sequences"].extend(instance.get_sequences())
        
    def remove_sequence(self, sequence:str, name:str): #removes forward and reverse versions of a sequence from all dictionaries, made to be used in a for loop iterating through the objects
        if self.name == name:
            for key in self.sequence_dict.keys():
                self.sequence_dict[key] = [ i for i in self.sequence_dict[key] if i != sequence and i != sequence[::-1]]
          
    def add_abbreviations(self, seq_abb_dict:dict[str,str]):
        for key in self.sequence_dict.keys():
            for idx, item in enumerate(self.sequence_dict[key]):
                self.sequence_dict[key][idx]=item + "," + seq_abb_dict[item]
class Hairpin(Motif):

    def __init__(self, motif_json:list, bgsu_json:list):
        super().__init__(motif_json)
        try:self.rfam_lower_bound=int(motif_json["rfam_lower_bound"])
        except:pass
        try:self.rfam_upper_bound=int(motif_json["rfam_upper_bound"])
        except:pass
        try:self.get_instances(bgsu_json)
        except:
            print("The motif {mot} is not in bgsu_json, collection will continue without this part.".format(mot=self.name))
    
    def get_instances(self,bgsu:list):
        alignments=[]
        for i in range(len(bgsu)):
            ID=re.split("[.]",bgsu[i]["motif_id"])[0]
            if ID in self.instances:
                alignments.append(Instance("hairpin",ID,bgsu[i]["alignment"],int(bgsu[i]["num_nucleotides"])))
        self.instances = alignments
    
    def get_rfam_sequences(self):
        self.rfam_api_calls  = self.make_rfam_api_calls()
        self.rmfam_alignment = self.get_rfam_alignments()
        self.sequence_dict["rfam_sequences"] += self.extract_rmfam_sequences()

    def make_rfam_api_calls(self):
        calls=[]
        for entry in self.rfam_ids:
            call="https://rfam.org/motif/{mot}/alignment?acc={mot}&format=stockholm&download=0".format(mot=entry)
            calls.append(call)
        return calls

    def get_rfam_alignments(self):
        for call in self.rfam_api_calls:
            answer=requests.get(call)
            if answer.status_code == 200:
                self.rfam_api_calls.remove(call)
                decoded=answer.content.decode()
                Alignment = list(AlignIO.parse(StringIO(decoded), format="stockholm"))[0]
                return Alignment #since all the hairpins only have one single RMFAM ID, this works. If
                                 #I ever add this to internal loops I'll have to return a list of alignments
            else:
                raise ConnectionError("Error during API request for {mot}, request return:{code}".format(mot=self.name,code=answer.status_code))
    
    def extract_rmfam_sequences(self):
        sequences=[]
        for entry in self.rmfam_alignment._records: #type:ignore
            seq=[x.upper() for x in list(entry.seq[self.rfam_lower_bound:self.rfam_upper_bound]) if x!= "-"]
            if "N" not in seq:
                sequences.append(''.join(seq))
            else:pass
        return list(set(sequences))

class Internal(Motif):

    def __init__(self, motif_json:list,bgsu_json:list):
        super().__init__(motif_json)
        self.get_instances(bgsu_json)

    def get_instances(self,bgsu:list):
        alignments=[]
        for i in range(len(bgsu)):
            ID=re.split("[.]",bgsu[i]["motif_id"])[0]
            if ID in self.instances:
                alignments.append(Instance("internal",ID,bgsu[i]["alignment"],int(bgsu[i]["num_nucleotides"]),int(bgsu[i]["chainbreak"])))
        self.instances=alignments

    def get_rfam_sequences(self): #Since I went through the effort of writing down every rfam internal sequence in that file, this is where they come from.
        rfam_internals_path=os.path.dirname(os.path.realpath(__file__))+ "/data/rfam_internals_fw.csv"
        with open(rfam_internals_path,"r")  as file:
            rows=file.readlines()
        split_rows=[x.split(",") for x in rows] #idk why but I have to do the splitting in a separate step, creating an extra list but the file aint big so should be no problem
        self.sequence_dict["rfam_sequences"].extend(x[0] for x in split_rows if x[1].strip() == self.abbreviation)

    def sort_sequences(self):
        keys = list(self.sequence_dict.keys())
        for key in keys:
            self.sequence_dict["i"+key] = [x for x in self.sequence_dict[key] if "$" in x]
            self.sequence_dict["b"+key] = [x for x in self.sequence_dict[key] if "$" not in x]
        for key in keys:
            del self.sequence_dict[key]

class Instance:
    def __init__(self,looptype,id:str,alignments:dict,len:int,chainbreak:int=0):
        self.loop_type      = looptype
        self.id             = id
        self.alignments     = alignments
        self.length         = len
        self.chainbreak     = chainbreak #chainbreak from the .json files, does not necessarily apply to api sequences
        self.api_call       = "http://rna.bgsu.edu/correspondence/pairwise_interactions_single?selection_type=loop_id&selection=" #full api call that every instance needs
 
    def get_sequences(self)-> list: #Extra function, could easily put this into __init__ but to make the algorithm more readable by calling "get sequences" on all instances
       return self.get_sequences_json() + self.get_sequences_api(self.api_requests())

    def api_requests(self) ->list[list[str]]:
        api_requests  = []
        api_responses = []
        for loop in self.alignments.keys():
            request = self.api_call+loop
            api_requests.append(request)
        while len(api_requests):
            for call in api_requests:
                response=requests.get(call)
                if response.status_code == 200:
                    api_requests.remove(call)
                    decoded=response.content.decode()
                    split=decoded.split()
                    api_responses.append(split)
                else:
                    sleep(1)
        return api_responses

    def get_sequences_json(self) -> list: #returns list of sequences of all Loops in this instance, taken from the provided .json
        sequences=[]
        if self.loop_type == "hairpin":
            for loop in self.alignments.values():
                sequence = "".join( [self.get_nucleotide_element(x,3) for x in loop[1:-1]])
                if len(sequence) > 3: #Important length check for Hairpin Loops as I want to filter out 3 nucleotide non bulged UNCGs and GNRAs
                    sequences.append(sequence) #because the database is inconsistant with the UNCGs specifically, listing all their second nucleotides as bulged
        if self.loop_type == "internal":
            for loop in self.alignments.values():
                alpha = "".join( [self.get_nucleotide_element(x,3) for x in loop[1 : self.chainbreak  -1 ]] )
                omega = "".join( [self.get_nucleotide_element(x,3) for x in loop[self.chainbreak +1 : -1 ]] )
                sequences.append(self.FUSION(alpha,omega))
        return list(set(sequences))

    def get_sequences_api(self,api:list) -> list: #returns list of sequences of all Loops in that instance, taken from the bgsu API
        sequences=[]
        r=re.compile("[|]")
        for response_list in api:
            nucleotides=[x for x in response_list if r.search(x)]
            if self.loop_type == "hairpin":
                sequences.append("".join( [self.get_nucleotide_element(x,3) for x in nucleotides[1:-1]])) #it's easy for hairpins because no sequence break, what about internals tho?
            if self.loop_type == "internal":
                seq_break=self.sequence_break_api(nucleotides) #seq_break is the last nucleotide of the first part of the sequence
                if seq_break:
                    alpha = "".join( [self.get_nucleotide_element(x,3) for x in nucleotides [1 : seq_break ]])
                    omega = "".join( [self.get_nucleotide_element(x,3) for x in nucleotides [seq_break + 2 : -1]])
                    sequences.append(self.FUSION(alpha,omega))
        return list(set(sequences))

    def sequence_break_api(self,nucleotides:list) -> int|bool:
        positions=[ self.get_nucleotide_element(x,4) for x in nucleotides ]
        for i in range(len(positions)-1):
            Diff = int(positions[i+1]) - int(positions[i])
            if abs(Diff) > 3: #This is where bulge size is theoretically limited, if there are two internal loop parts that are closer together than 3, the sequence break will be detected as faulty (min hairpin size is 3).
                return i
            else:pass
        print("Sequence break for {nuc} [{inst}] was less than 3 or not found. Sequence has been removed, will not be considered further.".format(nuc=self.get_nucleotide_element(nucleotides[0],0)[5:],inst=self.id))
        return False

    def FUSION(self,a,b) -> str:
        if len(a) > 0 and len(b) > 0:
            sequence = a + "$" + b #type:str
        else:
            sequence = a + b #concatenate them together, this way it doesnt matter which one has length 0. Later I can check for $ in the string to decide if its bulge or internal.
        return sequence

    def get_nucleotide_element(self,nucleotide:str,number:int) ->str:
        split=nucleotide.split("|")        
        element=split[number]
        return element

def load_local_json(file_name:str) -> list: #load local json versions in case the server is not reachable
    local_file = os.path.dirname(os.path.realpath(__file__)) + "/data/" + file_name
    with open(local_file) as json_file:
        motifs_json=json.load(json_file)
    return motifs_json
    
def load_bgsu_json(call:str) ->list: #Tries to download the latest json from bgsu 5 times, if all 5 attempts fail it takes a locally provided 3.81 version from the data folder.
    i = 0
    while i < 6:
        response= requests.get(call)
        if response.status_code == 200:
            return json.loads(response.content.decode())
        else:
            i += 1
    raise ConnectionError("Could not establish connection to BGSU servers, exiting...")

def load_jsons() -> list[Hairpin | Internal]: #The load_bgsu function has a backup hl_3.81/il_3.81 in case the most up to date versions can not be fetched from the bgsu servers.
    hl=load_bgsu_json("http://rna.bgsu.edu/rna3dhub/motifs/release/hl/current/json")
    il=load_bgsu_json("http://rna.bgsu.edu/rna3dhub/motifs/release/il/current/json")
    motif_json=load_local_json("motifs.json")
    motifs=[] #type:list['Hairpin|Internal']
    for motif in motif_json:
        if motif["loop_type"] == "hairpin":
            class_motif = Hairpin(motif,hl)
            motifs.append(class_motif)
        elif motif["loop_type"] == "internal":
           class_motif = Internal(motif,il)
           motifs.append(class_motif)
        else:pass
    return motifs

def dupe_check(motif_list:list[Hairpin|Internal])-> dict[str:str]: #reworked dupe check that not only checks for duplicate sequences but also creates a dictionary with sequence:abbreviations pairs (for managing duplicates).
    seen={} #type:dict[str,str]
    for motif in motif_list:  
        for sequence in list(set(flatten([list(set(motif.sequence_dict["bgsu_sequences"])), list(set(motif.sequence_dict["rfam_sequences"]))]))):
            if sequence not in seen.keys():
                seen[sequence] = motif.abbreviation
                seen[sequence[::-1]] = motif.abbreviation
            else:
                if seen[sequence] != motif.abbreviation:
                    print("Ambiguous sequence found: {seq}, present in {a} and {b}, converting first instance to lower case and keeping {c}...".format(seq=sequence, a = seen[sequence], b = motif.abbreviation, c= seen[sequence].lower()))
                    seen[sequence] = seen[sequence].lower()
                    seen[sequence[::-1]] = seen[sequence[::-1]].lower()
    return seen
           
def create_hexdumbs(motif_list: list[Hairpin|Internal], abbreviations: dict):
    keys=["bgsu_fw","bgsu_rv","bgsu_both","rfam_fw","rfam_rv","rfam_both","both_fw","both_rv","both_both"] #type:list[str]
    hsequence_dict = defaultdict(list, { key:[] for key in keys })
    isequence_dict = defaultdict(list, { key:[] for key in keys })
    bsequence_dict = defaultdict(list, { key:[] for key in keys })
    for mot in motif_list:
        if isinstance(mot, Hairpin):
            mot.add_abbreviations(abbreviations)
            sort_seq_dictionaries(mot,hsequence_dict)
        if isinstance(mot, Internal):
            mot.add_abbreviations(abbreviations)
            mot.sort_sequences()
            sort_seq_dictionaries(mot, isequence_dict,"i")
            sort_seq_dictionaries(mot, bsequence_dict,"b")   
    with open(os.path.dirname(os.path.realpath(__file__))+"/mot_header2.hh","x") as file:
        for key in keys:
            file.write(sequences2header(hsequence_dict[key],"h"+key))
            file.write(sequences2header(isequence_dict[key],"i"+key))
            file.write(sequences2header(bsequence_dict[key],"b"+key))

def sort_seq_dictionaries(motif: Hairpin | Internal, seq_dict: dict[str, list[str]], looptype: str = ""): #modifies the dictionary inplace, so no return needed
    seq_dict["bgsu_fw"].extend(list(set(motif.sequence_dict[looptype+"bgsu_sequences"])))
    seq_dict["bgsu_rv"].extend(list(set(motif.sequence_dict[looptype+"bgsu_reverse"])))
    seq_dict["bgsu_both"].extend(list(set(flatten([motif.sequence_dict[looptype+"bgsu_sequences"],motif.sequence_dict[looptype+"bgsu_reverse"]]))))
    seq_dict["rfam_fw"].extend(list(set(motif.sequence_dict[looptype+"rfam_sequences"])))
    seq_dict["rfam_rv"].extend(list(set(motif.sequence_dict[looptype+"rfam_reverse"])))
    seq_dict["rfam_both"].extend(list(set(flatten([motif.sequence_dict[looptype+"rfam_sequences"],motif.sequence_dict[looptype+"rfam_reverse"]]))))
    seq_dict["both_fw"].extend(list(set(flatten([motif.sequence_dict[looptype+"bgsu_sequences"],motif.sequence_dict[looptype+"rfam_sequences"]]))))
    seq_dict["both_rv"].extend(list(set(flatten([motif.sequence_dict[looptype+"bgsu_reverse"],motif.sequence_dict[looptype+"rfam_reverse"]]))))
    seq_dict["both_both"].extend(list(set(flatten([flatten([motif.sequence_dict[looptype+"bgsu_sequences"],motif.sequence_dict[looptype+"rfam_sequences"]]),flatten([motif.sequence_dict[looptype+"bgsu_reverse"],motif.sequence_dict[looptype+"rfam_reverse"]])]))))

def flatten(xss:list[list[str]]) -> list:
    return [x for xs in xss for x in xs]

def sequences2header(seq_set:list,name:str)->str:
    joined_seq_set="\n".join(seq_set)
    out=[]
    out.append('static unsigned char {var_name}[] = {{'.format(var_name=name))
    data =[ joined_seq_set[ i : i+12 ] for i in range(0, len(joined_seq_set), 12) ]
    for i,x in enumerate(data):
        line=', '.join((["0x{val:02x}".format(val=ord(c)) for c in x]))
        out.append('  {lined}{comma}'.format(lined=line,comma=',' if i <len(data)-1 else ''))
    out.append('};')
    out.append('static unsigned int {var_name}_len = {data_len};\n'.format(var_name=name,data_len=len(joined_seq_set)))
    return '\n'.join(out)

if __name__ == "__main__":
    motifs=load_jsons()
    for motif in motifs:
        if len(motif.instances):
            motif.get_bgsu_sequences()
            motif.sequence_dict["bgsu_reverse"]=motif.reverse_sequences(motif.sequence_dict["bgsu_sequences"])
            print(motif.name)
        if len(motif.rfam_ids):
            motif.get_rfam_sequences()
            motif.sequence_dict["rfam_reverse"]=motif.reverse_sequences(motif.sequence_dict["rfam_sequences"])
            print(motif.name)
        if sys.argv[1] == "-r":
            motif.remove_sequence("UUCAA","GNRA")
            motif.remove_sequence("UACG","GNRA")
            motif.remove_sequence("GUGA","UNCG")
    seq_abbreviation_dict=dupe_check(motifs)
    create_hexdumbs(motifs,seq_abbreviation_dict)