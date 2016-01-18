#!/usr/bin/env python
"""Tokenize, tag and parse Swedish plain text data.

This was originally the pipeline by Filip Salomonsson for the Swedish
Treebank (using hunpos for tagging), later modified by Robert Östling to use
efselab and Python 3.
"""

__authors__ = """
Filip Salomonsson <filip.salomonsson@gmail.com>
Robert Östling <robert.ostling@helsinki.fi>
"""

import re
import os
import sys
import codecs
import pickle
from datetime import datetime
import zlib, base64

ABBREVS = pickle.loads(zlib.decompress(base64.b64decode("""
eJxdlDtv6zAMhXf9kkyC5bfWoujSoUMDrYJbx22Rh43YCG7+eOd7DiU5vhcoAousyI+HpHb9ZNTO
PZ10p5xWy5QrOWg1FWreuYFWdwm+UrlBX+Cq6Doo18NYK3fwvZoa2hblbrC1yi3+piZL25tyczCb
TLk3P9NjDF1nhT/YkfTsz7AWMfDrleaSofE5GUl41sMpgBgk5QkoRvL2yt1pR+Le32G1MbxW4ReF
ZbxzxpU85U7hcskv4fJUNUvLWTBry6toFa68pplcuSSfJc0xxgLCrI8MJQzjfAuOAvlxoLAmSjWG
8oucco0UoAgCLJ/xDhVYPnlHCEbJFPKlsIAZ9awlcLOKGnyt6EqPXUHRxoyIaipNVFuz3OACykH3
dArJBxTqaAfIx8l3sFcR/oFQAmERgFIAfhAe/zDQBYIfPy9+gNPGEvr7Ca6Kenh+T5WJdEfagTD7
I6xF7OyNJcNRsrk3P8MlEPtVwQoE+6BgJQjvMRbSv0ss+6A+/OHUZmTG51RvusHu1rEbaG9d/HNL
iq3LcBHV1nEqo9p1nQasbiJeSNUSTlIJxXBduRtQDNcA3gjHUxS8kT2k4E0RxemCDE1JfTrK0FTp
ihY3KZp6XeAmrAY6I/e4G/I9NRs1xu2OtKLKKEW0my2BJ64I7MLzvLalBc9zaEub1uRCu2zJBda0
oWli0hy2iYjZbBi39AzZTMkJLisg/S3esiDBgY4iyrxpjwXNPrTHCs2k3FeQ1AJo8l/U1ArSy6MR
FigvsRE2zen6asmkhmcrC6Oq47abLE/rbrJ1Yx7dMFm51mGysDo6sZqsXmfJZGl3O0LRKcvb+ZHO
dXD+75gxMkKxZ8akYZbJM0ZmmaNnzGaWv9NdmeVvuVg9Hsz1ld0+s+GdRW9/xdOyub+0A03/BU99
rSo=
""")))

class PeekableIterator:
    def __init__(self, iterable):
        self._iterable = iter(iterable)
        self._cache = []

    def __iter__(self):
        return self

    def _fill_cache(self, n):
        if n is None:
            n = 1
        while len(self._cache) < n:
            self._cache.append(next(self._iterable))

    def __next__(self, n=None):
        self._fill_cache(n)
        if n is None:
            value = self._cache.pop(0)
        else:
            value = [self._cache.pop(0) for i in range(n)]
        return value

    def peek(self, n=None):
        self._fill_cache(n)
        if n is None:
            value = self._cache[0]
        else:
            value = [self._cache[i] for i in range(n)]
        return value

# Define the tokenizer
tokenizer_re = re.compile(r"""
    \w+(?:(?=[^/])\S\w+)*-?    # word-like stuff
    |                          # ...or...
    [+.]?\d+(?:[\s:/,.-]\d+)*  # numeric expressions
    |                          # ...or...
    (?P<para>\n(\s*\n)+)       # paragraph break
    |
    (?P<char>\S)(?P=char)+
    |
    \S                         # single non-space character
    """, re.UNICODE | re.VERBOSE)

def tokenize(data):
    for match in tokenizer_re.finditer(data):
        if match.group("para") is not None:
            yield None
        else:
            yield match.group(0)


def join_abbrevs(abbrevs, tokens):
    abbrev_prefixes = set()
    for abbrev in abbrevs:
        for i in range(len(abbrev)):
            abbrev_prefixes.add(abbrev[:i+1])

    if abbrevs:
        max_abbrev_length = max([len(abbrev) for abbrev in abbrevs])
    else:
        max_abbrev_length = 0
    tokens = PeekableIterator(tokens)
    was_abbrev = False

    for token in tokens:
        # Check if any abbreviations start with this token
        if (token,) in abbrev_prefixes:
            longest_candidate = None
            for i in range(max_abbrev_length):
                try:
                    # Peek ahead
                    candidate = (token,) + tuple(tokens.peek(i+1))
                    if candidate not in abbrev_prefixes:
                        break
                    # Check if we've built a known abbrev.
                    if candidate in abbrevs:
                        # Exclude final "." if the sentence ends with this abbrev.
                        next_token = tokens.peek(i+1)[-1]
                        if token == "." and next_token is None:
                            break

                        # Emit the normalized abbrev
                        longest_candidate = candidate
                        break
                except StopIteration:
                    # Tried to peek beyond EOF
                    break
            if longest_candidate:
                # Skip over the used tokens
                for _ in longest_candidate[:-1]:
                    next(tokens)
                yield abbrevs[longest_candidate]
                was_abbrev = True
            else:
                yield token
        else:
            # Token not known to start an abbr.; carry on.
            yield token
            # Aaand now for sentence segmentation.
            next_token = tokens.peek()
            if None not in (token, next_token) and \
                    (not was_abbrev) and \
                    token[-1] in ".:!?" \
                    and next_token[0].isupper():
                yield None
            was_abbrev = False


#from itertools import takewhile
def group_sentences(tokens):
    """Group tokens into sentences, based on None tokens"""
    sentence = []
    for token in tokens:
        if token is None:
            if sentence: yield sentence
            sentence = []
        else:
            sentence.append(token)
    if sentence: yield sentence

def tagged_to_tagged_conll(tagged, tagged_conll):
    """Read a .tag file and write to the corresponding .tagged.conll file"""
    s_id = 1
    t_id = 1
    for line in tagged:
        line = line.strip()
        if not line:
            print(line, file=tagged_conll) 
            s_id += 1
            t_id = 1
            continue
        fields = line.split('\t')
        token = fields[0]
        tag = fields[1]
        lemma = '_' if len(fields) < 3 else fields[2]
        if "|" in tag:
            pos, morph = tag.split("|", 1)
        else:
            pos = tag
            morph = "_"
        print("%s\t%s\t%s\t%s\t%s\t%s" % (
            "%d" % t_id,
            token,
            lemma,
            pos,
            pos,
            morph), file=tagged_conll)
        t_id += 1


if __name__ == '__main__':
    import fileinput
    import tempfile
    import shutil
    
    from subprocess import Popen, PIPE

    from optparse import OptionParser

    # Set some sensible defaults
    SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
    TAGGING_MODEL = os.path.join(SCRIPT_DIR, "suc.bin")
    LEMMATIZATION_MODEL = "suc-saldo.lemmas"
    PARSING_MODEL = "swemalt-1.7.2"
    MALT = os.path.join(SCRIPT_DIR, "maltparser-1.7.2")

    # Set up and parse command-line options
    usage = "usage: %prog --output-dir=DIR [options] FILENAME [...]"
    op = OptionParser(usage=usage)
    op.add_option("-o", "--output-dir", dest="output_dir", metavar="DIR",
                  help="set target directory for output (Required.)")
    op.add_option("--tokenized", dest="tokenized", action="store_true",
                  help="Generate tokenized output file(s) (*.tok)")
    op.add_option("--tagged", dest="tagged", action="store_true",
                  help="Generate tagged output file(s) (*.tag)")
    op.add_option("--lemmatized", dest="lemmatized", action="store_true",
                  help="Also lemmatize the tagged output file(s) (*.tag)")
    op.add_option("--parsed", dest="parsed", action="store_true",
                  help="Generate parsed output file(s) (*.conll)")
    op.add_option("--all", dest="all", action="store_true",
                  help="Equivalent to --tokenized --tagged --parsed")
    op.add_option("-m", "--tagging-model", dest="tagging_model",
                  default=TAGGING_MODEL, metavar="FILENAME",
                  help="Model for PoS tagging")
    op.add_option("-l", "--lemmatization-model", dest="lemmatization_model",
                  default=LEMMATIZATION_MODEL, metavar="MODEL",
                  help="MaltParser model file for parsing")
    op.add_option("-p", "--parsing-model", dest="parsing_model",
                  default=PARSING_MODEL, metavar="MODEL",
                  help="MaltParser model file for parsing")
    op.add_option("--malt", dest="malt", default=MALT, metavar="DIR",
                  help="Path to the MaltParser directory")
    op.add_option("--no-delete", dest="no_delete", action="store_true",
                  help="Don't delete temporary working directory.")

    options, args = op.parse_args()
    if options.all:
        options.tokenized = True
        options.tagged = True
        options.parsed = True

    if not (options.tokenized or options.tagged or options.parsed):
        op.error("Nothing to do! Please use --tokenized, --tagged and/or --parsed (or --all)")

    # If no target directory was given: write error message and exit.
    if not options.output_dir:
        op.error("No target directory specified. Use --output-dir=DIR")

    if not args:
        op.error("Please specify at least one filename as input.")

    # Set up (part of) command lines
    jarfile = os.path.join(os.path.expanduser(options.malt), "maltparser-1.7.2.jar")

    # Make sure we have all we need
    if options.tagged and not os.path.exists(options.tagging_model):
        sys.exit("Can't find tagging model: %s" % options.tagging_model)
    if options.lemmatized and not options.tagged:
        sys.exit("Can't lemmatize without tagging.")
    if options.lemmatized and not os.path.exists(options.lemmatization_model):
        sys.exit("Can't find lemmatizer model file %s." %
                 options.lemmatization_model)
    if options.parsed and not os.path.exists(jarfile):
        sys.exit("Can't find MaltParser jar file %s." % jarfile)
    if options.parsed and not os.path.exists(options.parsing_model+".mco"):
        sys.exit("Can't find parsing model: %s" % options.parsing_model+".mco")

    if options.tagged or options.parsed:
        import suc
        with open(options.tagging_model, 'rb') as f:
            tagger_weights = f.read()

    # Set up the working directory
    tmp_dir = tempfile.mkdtemp("-stb-pipeline")
    if options.parsed:
        shutil.copy(os.path.join(SCRIPT_DIR, options.parsing_model+".mco"),
                    tmp_dir)

    lemmatizer = None
    if options.lemmatized:
        import lemmatize
        lemmatizer = lemmatize.SUCLemmatizer()
        lemmatizer.load(options.lemmatization_model)

    # Process each input file
    for filename in args:
        name_root, ext = os.path.splitext(filename)
        basename = os.path.basename(name_root)

        def output_filename(suffix):
            return os.path.join(tmp_dir, "%s.%s" % (basename, suffix))

        # Set up output filenames
        tokenized_filename = output_filename("tok")
        tagged_filename = output_filename("tag")
        tagged_conll_filename = output_filename("tag.conll")
        parsed_filename = output_filename("conll")
        log_filename = output_filename("log")


        # The parser command line is dependent on the input and
        # output files, so we build that one for each data file
        parser_cmdline = ["java", "-Xmx2000m",
                          "-jar", jarfile,
                          "-m", "parse",
                          "-i", tagged_conll_filename,
                          "-o", parsed_filename,
                          "-w", tmp_dir,
                          "-c", os.path.basename(options.parsing_model)]


        # Open the log file for writing
        log_file = open(log_filename, "w")

        print("Processing %s..."% (filename), file=sys.stderr)

        # Read input data file
        data = codecs.open(filename, "r", "utf-8").read()


        #########################################
        # Tokenization, tagging and lemmatization

        # Basic tokenization
        tokens = tokenize(data.strip())

        # Handle sentences and abbreviations
        marked = join_abbrevs(ABBREVS, tokens)

        # Chop it into sentences based on the markers that are left
        sentences = group_sentences(marked)

        # Write tokenized data to output dir, optionally tag as well
        tokenized = None
        if options.tokenized:
            tokenized = codecs.open(tokenized_filename, "w", "utf-8")

        tagged = None
        if options.tagged or options.parsed:
            tagged = open(tagged_filename, "w")

        for s_id, sentence in enumerate(sentences):
            for t_id, token in enumerate(sentence):
                print(token, file=tokenized)
            print(file=tokenized)
            if tagged:
                tags = suc.tag(tagger_weights, sentence)
                if lemmatizer:
                    for token, tag in zip(sentence, tags):
                        lemma = lemmatizer.predict(token, tag)
                        print(token + '\t' + tag + '\t' + lemma, file=tagged)
                else:
                    for token, tag in zip(sentence, tags):
                        print(token + '\t' + tag, file=tagged)
                print(file=tagged)

        if tokenized: tokenized.close()
        if tagged: tagged.close()
    
        if options.tokenized:
            shutil.copy(tokenized_filename, options.output_dir)
    
        if options.tagged:
            shutil.copy(tagged_filename, options.output_dir)

        #########
        # Parsing

        if options.parsed:
            # Conversion from .tag file to tagged.conll (input format for the parser)
            tagged_conll_file = codecs.open(tagged_conll_filename, "w", "utf-8")
            tagged_to_tagged_conll(codecs.open(tagged_filename, "r", "utf-8"),
                                   tagged_conll_file)
            tagged_conll_file.close()

            # Run the parser
            returncode = Popen(parser_cmdline,
                               stdout=log_file, stderr=log_file).wait()
            if returncode:
                sys.exit("Parsing failed! Log file may contain "
                         "more information: %s" % log_filename)

            if options.parsed:
                shutil.copy(parsed_filename, options.output_dir)

        # end: if options.parsed

        log_file.close()

        print("done.", file=sys.stderr)


    ##########
    # Clean up

    if not options.no_delete:
        shutil.rmtree(tmp_dir)
    else:
        print("Leaving working directory as is: %s" % tmp_dir, file=sys.stderr)
