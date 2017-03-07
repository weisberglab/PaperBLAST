#!/usr/bin/perl -w
# The first phase of the pipeline: downloading
use strict;
use Getopt::Long;
use FindBin qw($Bin);
use lib "$Bin/../lib";
use pbutils;

my @allsteps = qw{oa am refseq generif pubmed uniprot ecocyc};
my $dosteps = join(",", @allsteps);

my $usage = <<END
download.pl -dir downloads [ -steps $dosteps ] [ -test ]

This script downloads all of the inputs for building a PaperBLAST
database. These are all put into the specified directory. These inputs
are:

From EuropePMC:
The open access manuscripts, into dir/oa/*.xml.gz (21 GB)
	These are listed in dir/oa/files
The author manuscripts, into dir/am/*.tar.gz (8.5 GB)
	These are then exploded to give dir/am/*/*.xml
	The directory names are listed in dir/am/files

From RefSeq:
The compressed genbank format files, into dir/refseq/complete.*.gbff.gz (86 GB)
	These are listed in dir/refseq/files

From GeneRIF:
ftp://ftp.ncbi.nih.gov/gene/GeneRIF/generifs_basic.gz

From PubMed: metadata about articles (used primarily for finding snippets in abstracts)
	These are placed within dir/pubmed/updatefiles/*.xml.gz
        or dir/pubmed/baseline/*.xml.gz
	and are listed in dir/pubmed/updatefiles/files and dir/pubmed/baseline/files
	dir/ftp.ncbi.nlm.nih.gov/pubmed/updatefiles/*.xml.gz
	dir/ftp.ncbi.nlm.nih.gov/pubmed/updatefiles/*.xml.gz

From UniProt:
SwissProt (curated) annotations: dir/uniprot_sprot.dat.gz (0.5 GB)
SwissProt (curated) sequences: dir/uniprot_sprot.fasta.gz (0.1 GB)
TReMBL (non-curated) sequences: dir/uniprot_trembl.fasta.gz (16 GB)

From EcoCyc: ecoli.tar.gz (158 MB)
	This is then exploded to give the dir/ecocyc/version.number subdirectory,
	and then a symlink is created for dir/ecocyc_latest/

(All sizes for downloads are as of January 2017)

END
    ;

my $test;

sub maybe_run($) {
    my ($cmd) = @_;
    if (defined $test) {
        print STDERR "Would run\t$cmd\n";
    } else {
        print STDERR "Running $cmd\n";
        system($cmd) == 0
            || die "Error running $cmd: $!\n";
    }
}

sub maybe_wget($$) {
    my ($url, $file) = @_;
    if (defined $test) {
        print STDERR "Would wget $url into $file\n";
    } else {
        &wget($url, $file);
    }
}

my $dir;
die $usage
    unless GetOptions('dir=s' => \$dir, 'steps=s' => \$dosteps, 'test' => \$test)
    && @ARGV == 0;
die $usage unless defined $dir;
die "No such directory: $dir\n" unless -d $dir;

my @dosteps = split /,/, $dosteps;
my %dosteps = map { $_ => 1 } @dosteps;
my %allsteps = map { $_ => 1 } @allsteps;
foreach my $step (keys %dosteps) {
    die "Unrecognized step: $step\n" unless exists $allsteps{$step};
}

print STDERR "Test mode\n" if defined $test;

my $listfile = "$dir/listing.$$";

if (exists $dosteps{"oa"}) {
    print STDERR "Step oa\n";
    &mkdir_if_needed("$dir/oa");
    &wget("http://europepmc.org/ftp/oa/", $listfile);
    my @files = &ftp_html_to_files($listfile);
    @files = grep m/[.]xml[.]gz$/, @files;
    die "No .xml.gz files in oa, see $listfile" if @files == 0;
    print STDERR "Found " . scalar(@files) . " oa gz files to fetch\n";
    &write_list(\@files, "$dir/oa/files");
    foreach my $file (@files) {
        &maybe_wget("http://europepmc.org/ftp/oa/$file", "$dir/oa/$file");
    }
}

if (exists $dosteps{"am"}) {
    print STDERR "Step am\n";
    &mkdir_if_needed("$dir/am");
    &wget("http://europepmc.org/ftp/manuscripts/", $listfile);
    my @files = &ftp_html_to_files($listfile);
    @files = grep m/[.]xml[.]tar[.]gz$/, @files;
    die "No xml.tar.gz files in am, see $listfile" if @files == 0;
    print STDERR "Found " . scalar(@files) . " am gz files to fetch\n";
    &write_list(\@files, "$dir/am/files");
    foreach my $file (@files) {
        &maybe_wget("http://europepmc.org/ftp/manuscripts/$file", "$dir/am/$file");
    }
}

if (exists $dosteps{"refseq"}) {
    print STDERR "Step refseq\n";
    &mkdir_if_needed("$dir/refseq");
    &wget("ftp://ftp.ncbi.nlm.nih.gov/refseq/release/complete/", $listfile);
    my @files = &ftp_html_to_files($listfile);
    @files = grep m/^complete.*gbff[.]gz$/, @files;
    die "No complete*.gbff.gz files in refseq, see $listfile" if @files == 0;
    print STDERR "Found " . scalar(@files) . " refseq gbff.gz files to fetch\n";
    &write_list(\@files, "$dir/refseq/files");
    foreach my $file (@files) {
        &maybe_wget("ftp://ftp.ncbi.nlm.nih.gov/refseq/release/complete/$file", "$dir/refseq/$file");
    }
}

if (exists $dosteps{"generif"}) {
  print STDERR "Step generif\n";
  &maybe_wget("ftp://ftp.ncbi.nih.gov/gene/GeneRIF/generifs_basic.gz", "$dir/generifs_basic.gz");
  &maybe_run("gunzip $dir/generifs_basic.gz");
}

if (exists $dosteps{"pubmed"}) {
    print STDERR "Step pubmed\n";
    &mkdir_if_needed("$dir/pubmed");
    foreach my $part (qw{baseline updatefiles}) {
        &mkdir_if_needed("$dir/pubmed/$part");
        &wget("ftp://ftp.ncbi.nlm.nih.gov/pubmed/$part/", $listfile);
        my @files = &ftp_html_to_files($listfile);
        @files = grep m/[.]xml[.]gz$/, @files;
        die "No *.xml.gz files in pubmed $part, see $listfile" if @files == 0;
        print STDERR "Found " . scalar(@files) . " pubmed $part xml.gz files to fetch\n";
        &write_list(\@files, "$dir/pubmed/$part/files");
        foreach my $file (@files) {
            &maybe_wget("ftp://ftp.ncbi.nlm.nih.gov/pubmed/$part/$file", "$dir/pubmed/$part/$file");
        }
    }
}

if (exists $dosteps{"uniprot"}) {
    print STDERR "Step uniprot\n";
    foreach my $file (qw{uniprot_sprot.dat.gz uniprot_sprot.fasta.gz uniprot_trembl.fasta.gz}) {
        &maybe_wget("ftp://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/complete/$file",
                    "$dir/$file");
    }
}

if (exists $dosteps{"ecocyc"}) {
    print STDERR "Step ecocyc\n";
    &maybe_wget("http://brg-files.ai.sri.com/public/ecoli.tar.gz",
                "$dir/ecoli.tar.gz");
}

unlink($listfile);
if (defined $test) {
    print STDERR "Finished test\n";
} else {
    print STDERR "Downloads complete\n";
}
