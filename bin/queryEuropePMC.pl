#!/usr/bin/perl -w
use strict;
use JSON;
use LWP::Simple;
use URI::Escape;
use Time::HiRes qw( sleep gettimeofday tv_interval );
use Getopt::Long;
use IO::Handle; # for autoflush

my $wait = 1.0;
my $baseURL = "http://www.ebi.ac.uk/europepmc/webservices/rest/search";
my $maxQueries = -1;
# will add on query=, format=json, resulttype=core

my $usage = <<END
queryEuropePMC.pl -in queryprot -out out.tab
   [ -wait $wait ] [ -maxQueries 0 ]
   [ -URL $baseURL ]

The input format is tab-delimited with organism name, locus_tag or
other query term, query_id (and usually the sequence as well, but that
is ignored).

For each input line, the query will be of the form "locus_tag AND
genus", where genus is the first word of the organism name.

The output format is tab-delimited with the query_id and the json
format output (or empty if there was an error).

wait is the time between issuing queries, in seconds.

END
    ;

{
    my ($infile,$outfile,$debug);
    die $usage
        unless GetOptions('in=s' => \$infile,
                          'out=s' => \$outfile,
                          'wait=f' => \$wait,
                          'maxQueries=i' => \$maxQueries,
                          'URL=s' => \$baseURL,
                          'debug' => \$debug)
        && defined $infile && defined $outfile && @ARGV == 0;

    open(IN, "<", $infile) || die "Cannot read $infile\n";
    open(OUT, ">", $outfile) || die "Cannot write to $outfile\n";
    autoflush OUT 1; # so preliminary results appear
    my $nIn = 0;
    my $nSuccess = 0;
    my $nWithHits = 0;

    my $t0 = [gettimeofday];
    my $extra_wait = rand() * $wait/2;

    while(my $line = <IN>) {
        my $elapsed = tv_interval($t0);
        my $wait_time = $nIn * $wait + $extra_wait - $elapsed;
        if ($wait_time > 0) {
            print STDERR "Sleep $wait_time\n" if defined $debug;
            sleep($wait_time);
            print STDERR "Woke up\n" if defined $debug;
        }
        chomp $line;
        my ($organism,$locustag,$queryId) = split /\t/, $line;
        die "Invalid input line\n$line\n"
            unless defined $queryId
            && $organism ne ""
            && $locustag ne ""
            && $queryId ne "";
        my $genus = $organism; $genus =~ s/ .*//;
        die "Invalid organism $organism\n" if $genus eq "";
        my $query  = uri_escape("$locustag AND $genus");
        my $url = $baseURL . "?query=$query&format=json&resulttype=core";
        my $results = LWP::Simple::get("http://www.ebi.ac.uk/europepmc/webservices/rest/search?query=$query&format=json&resulttype=core");
        # In rare cases, may get XML back instead of a JSON object
        # This should not happen because of the uri_escape above,
        # but if it does, set it to empty
        $results = "" if !defined $results || $results =~ m/^[<]/;
        print OUT join("\t", $queryId, $results)."\n";
        $nIn++;
        $nSuccess++ if $results =~ m/"hitCount"/;
        $nWithHits++ if $results =~ m/"hitCount" *: *[1-9]/;
        last if $maxQueries > 0 && $nIn >= $maxQueries;
    }
    close(IN) || die "Error reading $infile\n";
    close(OUT) || die "Error writing $outfile\n";
    print STDERR "Queries $nIn Successful $nSuccess With-hits $nWithHits\n";
}
