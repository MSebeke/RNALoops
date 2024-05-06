import multiprocessing
import argparse
import subprocess
import os
from Bio import SeqIO
import gzip
import re
from numpy import mean
import sys
import logging

def get_cmdarguments():
    
    #Configure parser and help message
    parser = argparse.ArgumentParser(prog = 'RNALoops.py', 
                          description = 'A RNA secondary structure prediction programm with multiple functionalities for your convenience', 
                          epilog = 'GONDOR CALLS FOR AID! AND ROHAN WILL ANSWER!')

    #First positional argument, decide the algorithm that should be run on the input data. First argument with no flag.
    parser.add_argument(help = 'Specify which algorithm should be used', choices = ['motmfepretty', 'motpfc', 'motshapeX', 'mothishapes','motshapeX_pfc'], dest = 'algorithm',type=str)

    #Input has to be either a single sequence with specifier -I or a sequence file with -i [PATH_TO_FILE] (FASTA,  STOCKHOLM,  FASTQ).
    input = parser.add_mutually_exclusive_group(required = True)
    input.add_argument(  '-i',     '-inputFile', help = 'Set input path when using a file as input', type = argparse.FileType('r', encoding = 'UTF-8'), default = False, dest='iFile_path', nargs='?')
    input.add_argument(  '-I', '-inputSequence', help = 'Input a RNA sequence', type=str, dest='input_seq')
    parser.add_argument( '-n',   '-sequenceTag', help = 'If single sequence input is used you can specifiy a name for the input which will be used to mark it in output',type = str, dest='name', default="single_sequence", nargs ='?')
        
    #Command line arguments that control which algorithm is called with which options.
    parser.add_argument(  '-s',    '-subopt', help = 'Specify if mfe_subopt should be used,  usable exclusively with motmfepretty currently', action = 'store_true', default= False)
    parser.add_argument(  '-Q',  '-database', help = 'Specify from which database motifs should be used', choices = ['1', '2', '3'],  default = '3')
    parser.add_argument(  '-b', '-direction', help = 'Specify if 5->3,  3->5 or both motif versions should be used', choices = ['1', '2', '3'], default = '3')
    parser.add_argument(  '-k',    '-kvalue', help = 'k-value for k-best [int]', default = 10, type = int)
    parser.add_argument(  '-p',   '-hishape', help = 'Set hishape mode', choices = ['h', 'm', 'b'], default = 'h')
    parser.add_argument(  '-q',     '-shape', help = 'Set shape level', choices = [1, 2, 3, 4, 5], default = 2, type = int)
    parser.add_argument(  '-e',    '-energy', help = 'Specify energy range if mfe_subopt is used [float]', default = 1.0, type = float)
    parser.add_argument(  '-l',       '-log', help = 'Set log level, if log level is set to INFO or DEBUG all predictions log their time parameter', default='WARNING', dest = 'loglevel')
    parser.add_argument(  '-t',      '-time', help = 'Activate time logging, activating this will run all command with unix "time" utility', dest = 'time', action='store_const', const ="time", default ="")

    args=parser.parse_args()
    return args

def make_new_logger(lvl:str,name:str,form:str=""):
    logger=logging.getLogger(name)
    logger.setLevel(lvl.upper())
    handler   = logging.StreamHandler(sys.stderr)
    if form:
        formatter = logging.Formatter(fmt=form)
    else:
        formatter = logging.Formatter(fmt="%(asctime)s:%(levelname)s:%(message)s")
    handler.setFormatter(formatter)
    logger.propagate=False #Permanent propagate False since I'm not utilizing any subloggers and sublcasses. THis way I can just treat each loggers as a standalone, makes it easier.
    logger.addHandler(handler)
    return logger

class Process:
    def __init__(self,commandline_args:argparse.Namespace):

        #First of all create the logger, tracking progress. Set loglevel and return error if it's invalid.
        self.loglevel = commandline_args.loglevel.upper()
        
        numeric_level=getattr(logging,self.loglevel, None)
        if not isinstance(numeric_level, int):
            raise ValueError('Invalid log level: {lvl}'.format(lvl=self.loglevel))
        
        self.log=make_new_logger(self.loglevel,__name__)

        #Input parameters
        self.name = commandline_args.name
        
        if self.name is None:
            self.name = 'single_sequence'

        if commandline_args.iFile_path:
            self.iFile = commandline_args.iFile_path
            self.log.info('Input file path: {}'.format(self.iFile.name))
        else:
            self.input_seq = commandline_args.input_seq
            self.log.info('Run: {name}. Input sequence: {seq}'.format(name=self.name,seq=self.input_seq))

        #Other Process parameters
        self.algorithm = commandline_args.algorithm

        self.kvalue = commandline_args.k

        self.motif_source = commandline_args.Q

        self.subopt = commandline_args.s

        self.direction = commandline_args.b

        self.hishape_mode = commandline_args.p

        self.shape_level = commandline_args.q

        self.energy = commandline_args.e

        self.algorithm_path = self.find_algorithm_path(os.path.dirname(os.path.realpath(__file__)))
        
        self.time = commandline_args.time
        
        self.call_construct = self.call_constructor()
        
        if self.time:
            self.timelogger=make_new_logger('info','time','%(asctime)s:%(name)s:%(message)s') #time logger hard coded to info level, only gets initialized when time command is given.

        self.log.info('Process created successfully: {Process}'.format(Process=vars(self)))

    def find_algorithm_path(self,path:str) -> str: #Connect find_algorithm_path to call_constructor functions. This way its easier to implement finding the path! FIXME
        if self.algorithm == 'mothishapes':
            name = self.algorithm+'_'+self.hishape_mode
            for root, dirs, files in os.walk(path):
                if name in files:
                    alg_path=os.path.realpath(root,strict=True)
                    return alg_path#os.path.join(root, name)
                else:pass
            raise LookupError("Could not find algorithm. Make sure your chosen alrightm is installed within this folder or one of its subfolders.")
        else:
            for root, dirs, files in os.walk(path):
                if self.algorithm in files:
                    alg_path=os.path.realpath(root,strict=True)
                    return  alg_path#os.path.join(root, self.algorithm)
                else:pass
            raise LookupError("Could not find algorithm. Make sure your chosen alrightm is installed within this folder or one of its subfolders.")

    def call_constructor(self) -> str: #Constructs algorithm calls for goblins to go through with the given sequences
        match self.algorithm: #To be able to leave
            
            case 'motmfepretty': #the calls need to first go to the directory, otherwise no motifs cause the c++ path code is still fucky, change beginning to: {time} {path}/{algorithm} if you ever fix that.
                if self.subopt:
                    call = 'cd {path} && {time} ./{algorithm}_subopt -e {energy_value} -Q {database} -b {motif_direction} '.format(time=self.time, path=self.algorithm_path, algorithm=self.algorithm, energy_value=self.energy, database=self.motif_source, motif_direction=self.direction)
                else:
                    call = 'cd {path} && {time} ./{algorithm} -k {k} -Q {database} -b {motif_direction} '.format(time=self.time, path=self.algorithm_path, algorithm=self.algorithm, k=self.kvalue,database=self.motif_source,motif_direction=self.direction)
                    
            case 'motpfc':
                call = 'cd {path} && {time} ./{algorithm} -k {k} -Q {database} -b {motif_direction} '.format(time=self.time, path=self.algorithm_path, algorithm=self.algorithm, k=self.kvalue, database=self.motif_source, motif_direction=self.direction)
                
            case 'motshapeX':
                call = 'cd {path} && {time} ./{algorithm} -k {k} -Q {database} -b {motif_direction} -q {shapelvl} '.format(time=self.time, path=self.algorithm_path, algorithm=self.algorithm, k=self.kvalue,database=self.motif_source,motif_direction=self.direction,shapelvl=self.shape_level)
            
            case 'mothishapes':
                call = 'cd {path} && {time} ./{algorithm}_{mothishape_mode} -k {k} -Q {database} -b {motif_direction} '.format(time=self.time, path=self.algorithm_path, algorithm=self.algorithm, mothishape_mode=self.hishape_mode, k=self.kvalue,database=self.motif_source,motif_direction=self.direction,hishape=self.hishape_mode)
       
            case 'motshapeX_pfc':
                call = 'cd {path} && {time} ./{algorithm} -k {k} -Q {database} -b {motif_direction} -q {shapelvl} '.format(time=self.time, path=self.algorithm_path, algorithm=self.algorithm, k=self.kvalue,database=self.motif_source,motif_direction=self.direction,shapelvl=self.shape_level)
       
        return call

    def read_input_file(self) -> list:
        id_seq_tuples = []
        lens = []
        fileinfo=self.find_filetype() #Tuple made of the file type (fasta,fastq,stockholm) in fileinfo[0] and file zip status in fileinfo[1] (True= File is zipped, False= File is not zipped)
        if not fileinfo[1]: #checks for zip status, if the file is .gz it is passed to else where it is opened with gzip before being parsed by SeqIO
            for record in SeqIO.parse(self.iFile,fileinfo[0]):
                lens.append(len(str(record.seq)))
                tpl=(record.id,self.call_construct+re.sub('-','',str(record.seq))) #re.sub takes out dashes in case a multi sequence alignment is used as input, if there are no dashes (most fasta or fastq) nothing happens
                id_seq_tuples.append(tpl)
        else:
            with gzip.open(self.iFile.name,'rt') as handle:
                for record in SeqIO.parse(handle,fileinfo[0]):
                    lens.append(len(str(record.seq)))
                    tpl=(record.id,self.call_construct+str(record.seq))
                    id_seq_tuples.append(tpl)
        self.log.info('Reading successful. Input sequences: {len_idseq_tpls}. Average sequence length: {len}'.format(len_idseq_tpls=len(id_seq_tuples),len=round(mean(lens))))
        return id_seq_tuples
 
    def find_filetype(self) -> tuple[str,bool]: #Finds File type based on file ending
        if self.iFile.name.split('.')[-1] == 'gz' or self.iFile.name.split('.')[-1] == 'zip':
            file_extension = (self.iFile.name.split('.')[-2])
            zipped=True
        else:
            file_extension = (self.iFile.name.split('.')[-1])
            zipped=False
            
        match file_extension:
            case 'fasta'| 'fas' | 'fa' | 'fna' | 'ffn' | 'faa' | 'mpfa' | 'frn' | 'txt' | 'fsa': #All fasta file extensions accoring to Wikipedia FASTA format article
                self.log.info('Filetype identified as fasta, reading ...')
                return ('fasta',zipped)
            
            case 'fastq' | 'fq' :
                self.log.info('Filetype identified as fastq, reading...')
                return ('fastq',zipped)
    
            case 'stk' | 'stockholm' | 'sto':
                self.log.info('Filetype identified as stockholm,reading ...')
                return ('stockholm',zipped)
            
            case _:
                self.log.error('Could not identify file type as fasta, fastq or stockholm. If the file is zipped make sure it is .zip or .gz')
                sys.stdout.write('Couldnt recognize file type or zip of input file: {input}\n'.format(input=self.iFile.name))
                raise TypeError("Filetype was not recognized as fasta, fastq or stockholm format. Or file could not be unpacked, please ensure it is zipped with either .gz or .zip or unzipped")

    def Process(self):
        if hasattr(self,'input_seq'):
            self.single_process()
        else:
            self.multi_process()

    def single_process(self): #Fix single process to just make it print to stdout instead of this two way kinda bs.
        call = self.call_construct+self.input_seq
        result = subprocess.run(call,text=True,shell=True,capture_output=True)
        if not result.returncode:
            result_obj=transform_result(self.algorithm,self.name,result.stdout)
            subprocess_output=(result_obj,result.stderr)
        else:
            subprocess_output=(self.name,result.stderr)
        self.write_output(subprocess_output,False)

    def multi_process(self):
        records = self.read_input_file()
        Manager = multiprocessing.Manager()
        q       = Manager.Queue()
        Pool    = multiprocessing.Pool(processes=multiprocessing.cpu_count()-2)
        listening= multiprocessing.Process(target=self.listener,args=(q,)) #run the listener as a separate Process so it doesn't stop the rest of the scirpt
        listening.start() #start the listener, patiently waiting for 
        jobs = [] #list for all the worker processes
        for record in records:
            job = Pool.apply_async(worker,(record,q,self.algorithm))
            jobs.append(job) #append workers into the workerlist
        for job in jobs:
            job.get() #Get results from the workers to the q
        Pool.close()
        q.put('kill')
        Pool.join()
        listening.join()

    def listener(self,q): #This function has the sole write access to make writing the log mp save
        output_started=False
        while True:
            result=q.get() #get results from the q to the listener.
            if result == 'kill':
                break
            output_started=self.write_output(result,output_started)

    def write_output(self,result:tuple["ClassScoreClass|ClassPfc|str",str],ini:bool)-> bool:#Supports two output headers currently, Result Subclass is not recognized this just outputs the csv formatted results with no header
                                                                                            #Since I imported the Result class to this file, if I want to type hint the ClassScoreClass the whole expression has to be in quotation marks. (PEP606 Python Issue 45857)
        if isinstance(result[0],ClassScoreClass):
            if not ini:
                sys.stdout.write('ID,class1,score,class2\n')
            self.write_csv(result[0])
            if self.time:
                self.timelogger.info(result[0].id+':'+result[1].strip())
            return True
            
        elif isinstance(result[0],ClassPfc):
            if not ini:
                sys.stdout.write('ID,class,pfc,probability\n')
            self.write_csv(result[0])
            if self.time:
                self.timelogger.info(result[0].id+':'+result[1].strip())
            return True

        else:
            self.log.error('{name}:{error}'.format(name=result[0],error=result[1].strip()))
            return True
           
    def write_csv(self,result_obj:"ClassScoreClass|ClassPfc"):       
        for prediction in result_obj.results: #Writes the output in csv style.
            sys.stdout.write(result_obj.id+',')
            for i in range(len(prediction)-1):
                sys.stdout.write(prediction[i]+',')
            sys.stdout.write(prediction[i+1]+'\n')

class Result:
    def __init__(self, name,result):
        self.id      = name
        self.results = self.split_results(result) #results is a list of lists where list, the data within the list is specific for each Result subclass

    def split_results(self,result):
        split=result.split('\n')
        if split[-1] == '':
            split.pop() #Pops away the ending of the file as the pretty strings always end with a \n, leading to an empty list entry at the very end of each split
        return_list=[]
        for result in split:
            split_results=result.split('|')
            split_stripped_results= [x.strip() for x in split_results] #removes all whitespaces from results, makes it look nice
            return_list.append(split_stripped_results)
        return return_list

class ClassScoreClass(Result): #Sublcasses for different algorithm types, as generalized as possible.
    def __init__(self,name,results):
        super().__init__(name,results)

class ClassPfc(Result):
    def __init__(self, name, results):
        super().__init__(name,results)
        self.calculate_pfc_probabilities()

    def calculate_pfc_probabilities(self): #This function can easily be adapted for any of the Result subclasses, only the position of entry[1] has to be changed
        pfc_list=[] #Actually it doesn't really matter what I use to classify since it will always be classifying * partition algebra products. So I think this works always.
        for result in self.results: #iteratre through results within the motpfc result
            pfc_val=float(result[1]) #get the pfc float value from the position, results are lists made of [motif, pfc-value] in this case. Adjust entry[x] x as necessary
            pfc_list.append(pfc_val) #though the base 1 value will usually be correct, since partition function are usually used with only a classifying algebra
        pfc_sum=sum(pfc_list)
        for result in self.results:
            result.append(str(round(float(result[1])/pfc_sum,5)))

    def split_results(self, result):
        split=result.split('\n')
        split.pop() #Pops away the ending of the file as the pretty strings always end with a \n, leading to an empty list entry at the very end of each split
        split.pop() #gotta pop twice with pfc since it has an extra \n for some reason?
        return_list=[]
        for result in split:
            split_results=result.split('|')
            split_stripped_results= [ x.strip() for x in split_results]
            return_list.append(split_stripped_results)
        return return_list

#Non Process class function that need to be unbound to be pickle'able. See: https://stackoverflow.com/questions/1816958/cant-pickle-type-instancemethod-when-using-multiprocessing-pool-map, guess it kinda is possible it
#really isnt all that necessary though.

def worker(tpl:tuple, q:multiprocessing.Queue, alg:str): #I have no clue why but if you put this function into the Process class it will always exit with error 'cannot pickle '_io.TextIOWrapper', just leave it here
    result = subprocess.run(tpl[1],text=True,capture_output=True,shell=True)
    
    if not result.returncode: #double negative, this captures return_code=0, returned if subprocess.run worked
        stdout     = result.stdout
        stderr     = result.stderr
        output_obj = transform_result(alg,tpl[0],stdout)
        subprocess_output = (output_obj,stderr)

    else: #this captures return_code = 1, returned if subprocess.run did not work
        stderr     = result.stderr
        subprocess_output = (tpl[0],stderr)

    q.put(subprocess_output)

def transform_result(algorithm:str,name:str,results:str)->ClassScoreClass|ClassPfc: 
    match algorithm:
        case 'motmfepretty' | 'motshapeX' | 'mothishapes':#Class score class is for outputs 
            result_obj=ClassScoreClass(name,results)
        case 'motpfc' | 'motshapeX_pfc':
            result_obj=ClassPfc(name,results)
        case _:
            raise ValueError('Unknown algorithm, add case to transform_result function')
    return result_obj

if __name__=='__main__':
    args=get_cmdarguments()
    proc=Process(args)
    Process.Process(proc)