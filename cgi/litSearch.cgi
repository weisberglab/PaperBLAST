#!/usr/bin/perl -w
#######################################################
## litSearch.cgi
##
## Copyright (c) 2017 University of California
##
## Authors: Morgan Price
#######################################################
#
# Optional CGI garameters:
# query -- this should be the protein sequence in FASTA or UniProt or plain format,
#	or a VIMSS id, or a geneId in the database
# or
# more -- which geneId (in the database) to show the full list of papers for
#
# If none of these is specified, shows the query box, an example link, and some documentation

use strict;
use CGI qw(:standard Vars);
use CGI::Carp qw(warningsToBrowser fatalsToBrowser);
use Time::HiRes qw{gettimeofday};
use DBI;

sub fail($);
sub simstring($$$$$$$$$$$$$);
sub SubjectToGene($);

my $tmpDir = "../tmp";
my $blastall = "../bin/blast/blastall";
my $nCPU = 4;
my $base = "../data";
my $blastdb = "$base/uniq.faa";
my $sqldb = "$base/litsearch.db";
die "No such executable: $blastall" unless -x $blastall;
die "No such file: $blastdb" unless -e $blastdb;
die "No such file: $sqldb" unless -e $sqldb;

# If a gene has more papers than this, there is a "more" lnik to show all the information
# for that gene on a separate page

my $cgi=CGI->new;
my $query = $cgi->param('query') || "";
my $more_subjectId = $cgi->param('more') || "";
my $maxPapers = $more_subjectId ? 10000 : 8;

my $dbh = DBI->connect("dbi:SQLite:dbname=$sqldb","","",{ RaiseError => 1 }) || die $DBI::errstr;

my $documentation = <<END
<H3><A NAME="works">How It Works</A></H3>

<P>PaperBLAST builds a database of protein sequences that are linked to scientific publications. These links come from automated text searches against papers in <A HREF="http://europepmc.org/">EuropePMC</A> and from the manually-curated information about protein sequences in <A HREF="http://www.uniprot.org/">Swiss-Prot</A> and <A HREF="http://ecocyc.org">EcoCyc</A>. Given this database of proteins and a query sequence, PaperBLAST uses <A HREF="https://en.wikipedia.org/wiki/BLAST">protein-protein BLAST</A> to find similar sequences with E &lt; 0.001. As of February 2017, PaperBLAST links over 300,000 proteins to over 60,000 papers.

<P>To build PaperBLAST\'s database, we query every locus tag or <A HREF="https://www.ncbi.nlm.nih.gov/refseq/">RefSeq</A> protein id that appears in the open access part of EuropePMC (including the author manuscripts part). We obtain the protein sequences and identifiers from <A HREF="http://www.microbesonline.org/">MicrobesOnline</A> or from RefSeq. We use queries of the form "locus_tag AND genus_name" to try to ensure that the paper is actually discussing the gene as opposed to something else whose identifier happens to match a locus tag. Because EuropePMC indexes most recent biomedical papers, even if they are not open access, some of the links may be to papers that you cannot read (or that our computers cannot read).
We also query EuropePMC for every locus tag that appears in the 300 most-referenced genomes, so that a gene may appear in the PaperBLAST results even though none of the papers that mention it are open access.
Finally, we index proteins from Swiss-Prot if their curators identified experimental evidence for the protein\'s function (evidence code ECO:0000269), as well as every protein from <i> Escherichia coli</i> K-12 in EcoCyc. Most of these Swiss-Prot or EcoCyc entries include links to articles in <A HREF="http://www.ncbi.nlm.nih.gov/pubmed/">PubMed</A><sup>&reg;</sup>. (We also use PubMed<sup>&reg;</sup> abstracts to select snippets of text from papers that we do not have full-text access to if the abstract mentions a locus tag, a RefSeq id, or a UniProt accession.)</P>

<P>The code for PaperBLAST is available <A HREF="https://github.com/morgannprice/PaperBLAST">here</A>.

<H3><A NAME="secret">Secrets</A></H3>

<P>PaperBLAST cannot provide snippets for many of the papers that are published in non-open-access journals. This limitation applies even if the paper is marked as "free" on the publisher\'s web site and is available in PubmedCentral or EuropePMC. If a journal that you publish in is marked as "secret," please consider publishing elsewhere.

<center>by <A HREF="http://morgannprice.org/">Morgan Price</A>,
<A HREF="http://genomics.lbl.gov/">Arkin group</A><BR>
Lawrence Berkeley National Laboratory
</center>
END
    ;

my $title = "PaperBLAST";
# utf-8 because that is the encoding used by EuropePMC
print
    header(-charset => 'utf-8'),
    start_html($title),
    qq{<div style="background-color: #40C0CB; display: block; position: absolute; top: 0px; left: -1px; width: 100%; padding: 0.25em; z-index: 400;"><H2 style="margin: 0em;"><A HREF="litSearch.cgi" style="color: gold; font-family: 'Montserrat', sans-serif; font-style:italic; text-shadow: 1px 1px 1px #000000; text-decoration: none;">PaperBLAST &ndash; <small>Find papers about a protein or its homologs</small></A></H2></div><P style="margin: 0em;">&nbsp;</P>\n};

my $procId = $$;
my $timestamp = int (gettimeofday() * 1000);
my $filename = $procId . $timestamp;
my $seqFile = "$tmpDir/$filename.fasta";

# remove leading and trailing whitespace
$query =~ s/^\s+//;
$query =~ s/\s+$//;
if ($query =~ m/^VIMSS\d+$/i) {
  $query = &VIMSSToQuery($query);
} elsif ($query !~ m/\n/ && $query =~ m/[0-9_]/) {
  # a single line query with a number of underscore in it is assumed to be a gene id
  my $gene = $dbh->selectrow_hashref("SELECT * from Gene WHERE geneId = ?", {}, $query);
  die "Sorry, we have no papers linked to this gene id: $query\n" if ! $gene;
  my $geneId = $gene->{geneId};
  my $desc = $gene->{desc};
  my $org = $gene->{organism};
  my $dup = $dbh->selectrow_hashref("SELECT * from SeqToDuplicate WHERE sequence_id = ?", {}, $geneId);
  my $seqId = $dup ? $dup->{sequence_id} : $geneId;
  my $fastacmd = "../bin/blast/fastacmd";
  die "No such executable: $fastacmd" unless -x $fastacmd;
  system($fastacmd, "-s", $seqId, "-o", $seqFile, "-d", $blastdb) == 0 || die "fastacmd failed: $!";
  open(SEQ, "<", $seqFile) || die "Cannot read $seqFile";
  my $seq = "";
  while (my $line = <SEQ>) {
    next if $line =~ m/^>/;
    chomp $line;
    die "Invalid output from fastacmd" unless $line =~ m/^[A-Z*]+$/;
    $seq .= $line;
  }
  $query = ">$geneId $desc ($org)\n$seq\n";
}

my $seq;
my $def = "";
my $hasDef = 0;
if ($query =~ m/[A-Za-z]/) {
    $seq = "";
    my @lines = split /[\r\n]+/, $query;
    $def = shift @lines if @lines > 0 && $lines[0] =~ m/^>/;
    $def =~ s/^>//;
    foreach (@lines) {
        s/[ \t]//g;
        s/^[0-9]+//; # leading digit/whitespace occurs in UniProt format
        next if $_ eq "//";
        &fail("Error: more than one sequence was entered.") if m/^>/;
        &fail("Unrecognized characters in $_") unless m/^[a-zA-Z*]*$/;
        s/[*]/X/g;
        $seq .= uc($_);
    }
    $hasDef = 1 if $def ne "";
    $def = length($seq) . " a.a." if $def eq "";
}

if (!defined $seq && ! $more_subjectId) {
    my $exampleId = "3615187";
    my $refseqId = "WP_012018426.1";
    print
        start_form( -name => 'input', -method => 'POST', -action => 'litSearch.cgi'),
        p(br(),
          b("Enter a sequence in FASTA or Uniprot format: "),
          br(),
          textarea( -name  => 'query', -value => '', -cols  => 70, -rows  => 10 )),
        p(submit('Search'), reset()),
        end_form,
        p("Or see",
          a({ -href => "litSearch.cgi?vimss=$exampleId" }, "example results"),
            "for the putative alcohol dehydrogenase",
          a({ -href => "https://www.ncbi.nlm.nih.gov/protein/$refseqId",
                      -style => "color: black;" },
                    small("$refseqId,") ),
            "which is actually the regulator",
            a({ -href => "litSearch.cgi?vimss=$exampleId",
                -title => "Show PaperBLAST hits" },
              i("ercA")) . "."),
          $documentation;
} else {
    my $seqlen = length($seq);

    my $defLong;
    if ($more_subjectId) {
      $defLong = $more_subjectId;
    } else {
      my $initial = substr($seq, 0, 10);
      $initial .= "..." if $seqlen > 10;
      $initial = "$seqlen a.a., $initial" if $hasDef;
      $defLong = "$def ($initial)";
    }
    if ($more_subjectId) {
      print h3("Full List of Papers Linked to $more_subjectId");
    } else {
      print
        h3("PaperBLAST Hits for $defLong");
    }
    print "\n";
    my @hits = ();
    if ($more_subjectId) {
      push @hits, [ $more_subjectId, $more_subjectId, 100.0, 0, 0, 0, 0, 0, 0, 0, 0, 0 ];
    } else {
      open(SEQ, ">", $seqFile) || die "Cannot write to $seqFile";
      print SEQ ">$def\n$seq\n";
      close(SEQ) || die "Error writing to $seqFile";
      my $hitsFile = "$tmpDir/$filename.hits";
      system($blastall, "-p", "blastp", "-d", $blastdb, "-i", $seqFile, "-o", $hitsFile,
             "-e", 0.001, "-m", 8, "-a", $nCPU, "-F", "m S") == 0 || die "Error running blastall: $!";
      open(HITS, "<", $hitsFile) || die "Cannot read $hitsFile";
      while(<HITS>) {
        chomp;
        my @F = split /\t/, $_;
        push @hits, \@F;
      }
      close(HITS) || die "Error reading $hitsFile";
      unlink($seqFile);
      unlink($hitsFile);
    }
    my $nHits = scalar(@hits);
    if ($nHits == 0) {
        print p("Sorry, no hits to proteins in the literature.");
    } else {
        print p("Found $nHits similar proteins in the literature:"), "\n"
          unless $more_subjectId;

        my %seen_subject = ();
        my $li_with_style = qq{<LI style="list-style-type: none;" margin-left: 6em; >};
        my $ul_with_style = qq{<UL style="margin-top: 0em; margin-bottom: 0em;">};
        foreach my $row (@hits) {
            my ($queryId,$subjectId,$percIdentity,$alnLength,$mmCnt,$gapCnt,$queryStart,$queryEnd,$subjectStart,$subjectEnd,$eVal,$bitscore) = @$row;
            next if exists $seen_subject{$subjectId};
            $seen_subject{$subjectId} = 1;

            my $dups = $dbh->selectcol_arrayref("SELECT duplicate_id FROM SeqToDuplicate WHERE sequence_id = ?",
                                                {}, $subjectId);
            my @subject_ids = ($subjectId);
            push @subject_ids, @$dups;

            my @genes = map { &SubjectToGene($_) } @subject_ids;
            @genes = sort { $a->{priority} <=> $b->{priority} } @genes;
            my @headers = ();
            my @content = ();
            my %paperSeen = (); # to avoid redundant papers -- pmId.pmcId.doi => term => 1
            my %paperSeenNoSnippet = (); # to avoid redundant papers -- pmId.pmcId.doi => 1

            # Produce top-level and lower-level output for each gene (@headers, @content)
            # Suppress duplicate papers if no additional terms show up
            # (But, a paper could show up twice with two different terms, instead of the snippets
            # being merged...)
            foreach my $gene (@genes) {
                die "No subjectId" unless $gene->{subjectId};
                foreach my $field (qw{showName URL priority subjectId desc organism protein_length source}) {
                    die "No $field for $subjectId" unless $gene->{$field};
                }
                my @pieces = ( a({ -href => $gene->{URL}, -title => $gene->{source} }, $gene->{showName}),
                               $gene->{priority} <= 2 ? b($gene->{desc}) : $gene->{desc},
                               "from",
                               i($gene->{organism}) );
                # The alignment to show is always the one reported, not necessarily the one for this gene
                # (They are all identical, but only $subjectId is guaranteed to be in the blast database
                # and to be a valid argument for showAlign.cgi)
                push @pieces, &simstring(length($seq), $gene->{protein_length},
                                         $queryStart,$queryEnd,$subjectStart,$subjectEnd,
                                         $percIdentity,$eVal,$bitscore,
                                         $def, $gene->{showName}, $seq, $subjectId)
                    if $gene->{subjectId} eq $genes[0]{subjectId};
                if (exists $gene->{pmIds} && @{ $gene->{pmIds} } > 0) {
                    my @pmIds = @{ $gene->{pmIds} };
                    my %seen = ();
                    @pmIds = grep { my $keep = !exists $seen{$_}; $seen{$_} = 1; $keep; } @pmIds;
                    my $note = @pmIds > 1 ? scalar(@pmIds) . " papers" : "paper";
                    push @pieces, "(see " .
                        a({-href => "http://www.ncbi.nlm.nih.gov/pubmed/" . join(",",@pmIds) }, $note)
                        . ")";
                }
                push @headers, join(" ", @pieces);
                push @content, $gene->{comment} if $gene->{comment};
                my $nPaperShow = 0;
                foreach my $paper (@{ $gene->{papers} }) {
                    my @pieces = (); # what to say about this paper
                    my $snippets = [];
                    $snippets = $dbh->selectall_arrayref(
                        "SELECT DISTINCT * from Snippet WHERE geneId = ? AND pmcId = ? AND pmId = ?",
                        { Slice => {} },
                        $gene->{subjectId}, $paper->{pmcId}, $paper->{pmId})
                        if $paper->{pmcId} || $paper->{pmId};

                    my $paperId = join(":::", $paper->{pmId}, $paper->{pmcId}, $paper->{doi});
                    my $nSkip = 0; # number of duplicate snippets
                    foreach my $snippet (@$snippets) {
                        my $text = $snippet->{snippet};
                        my $term = $snippet->{queryTerm};
                        if (exists $paperSeen{$paperId}{$term}) {
                            $nSkip++;
                        } else {
                            $text =~ s!($term)!<B><span style="color: red;">$1</span></B>!gi;
                            push @pieces, "&ldquo;...$text...&rdquo;";
                        }
                    }
                    # ignore this paper if all snippets were duplicate terms
                    next if $nSkip == scalar(@$snippets) && $nSkip > 0;
                    $nPaperShow++;
                    if ($nPaperShow > $maxPapers) {
                      push @content, a({-href => "litSearch.cgi?more=".$subjectId},
                                       "More");
                      last;
                      next;
                    }
                    foreach my $snippet (@$snippets) {
                        my $term = $snippet->{queryTerm};
                        $paperSeen{$paperId}{$term} = 1;
                    }

                    # Add RIFs
                    my $rifs = [];
                    $rifs = $dbh->selectall_arrayref(qq{ SELECT DISTINCT * from GeneRIF
                                                        WHERE geneId = ? AND pmcId = ? AND pmId = ? },
                                                    { Slice => {} },
                                                    $gene->{subjectId}, $paper->{pmcId}, $paper->{pmId})
                      if $paper->{pmcId} || $paper->{pmId};
                    my $GeneRIF_def = a({ -title => "from Gene Reference into Function (NCBI)",
                                          -href => "https://www.ncbi.nlm.nih.gov/gene/about-generif",
                                          -style => "color: black; text-decoration: none; font-style: italic;" },
                                        "GeneRIF");
                    # just 1 snippet if has a GeneRIF
                    pop @pieces if @$rifs > 0 && @pieces > 1;
                    foreach my $rif (@$rifs) {
                      # normally there is just one
                      unshift @pieces, $GeneRIF_def . ": " . $rif->{ comment };
                    }

                    my $paper_url = undef;
                    my $pubmed_url = "http://www.ncbi.nlm.nih.gov/pubmed/" . $paper->{pmId};
                    if ($paper->{pmcId} && $paper->{pmcId} =~ m/^PMC\d+$/) {
                        $paper_url = "http://www.ncbi.nlm.nih.gov/pmc/articles/" . $paper->{pmcId};
                    } elsif ($paper->{pmid}) {
                        $paper_url = $pubmed_url;
                    } elsif ($paper->{doi}) {
                      if ($paper->{doi} =~ m/^http/) {
                        $paper_url = $paper->{doi};
                      } else {
                        $paper_url = "http://doi.org/" . $paper->{doi};
                      }
                    }
                    my $title = $paper->{title};
                    $title = a({-href => $paper_url}, $title) if defined $paper_url;
                    my $authorShort = $paper->{authors};
                    $authorShort =~ s/ .*//;
                    my $extra = "";
                    $extra = "(" . a({-href => $pubmed_url}, "PubMed") . ")"
                        if !$paper->{pmcId} && $paper->{pmId};
                    my $paper_header = $title . br() .
                        small( a({-title => $paper->{authors}}, "$authorShort,"),
                               $paper->{journal}, $paper->{year}, $extra);
                    
                    if (@pieces == 0) {
                        # Skip if printed already for this gene (with no snippet)
                        next if exists $paperSeenNoSnippet{$paperId};
                        $paperSeenNoSnippet{$paperId} = 1;

                        # Explain why there is no snippet
                        my $excuse;
                        my $short;
                        if ($paper->{access} eq "full") {
                          $short = "no snippet";
                          $excuse = "This term was not found in the full text, sorry.";
                        } elsif ($paper->{isOpen} == 1) {
                          if ($paper->{access} eq "abstract") {
                            $short = "no snippet";
                            $excuse = "This paper is open access but PaperBLAST only searched the the abstract.";
                          } else {
                            $short = "no snippet";
                            $excuse = "This paper is open access but PaperBLAST did not search either the full text or the abstract.";
                          }
                        } elsif ($paper->{isOpen} eq "") {
                          # this happens if the link is from GeneRIF
                          $short = "no snippet";
                          $excuse = "PaperBLAST did not search either the full text or the abstract.";
                        } elsif ($paper->{journal} eq "") {
                          $short = "secret";
                          $excuse = "PaperBLAST does not have access to this paper, sorry";
                        } else {
                            $short = "secret";
                            $excuse = "$paper->{journal} is not open access, sorry";
                        }
                        if ($excuse) {

                            my $href = a({-title => $excuse}, $short);
                            $paper_header .= " " . small("(" . $href . ")"); 
                        }
                    }
                    my $pieces = join($li_with_style, @pieces);
                    $pieces = join("", $ul_with_style, $li_with_style, $pieces, "</UL>")
                        if $pieces;
                    push @content, $paper_header . $pieces;
                }
            }
            my $content = join($li_with_style, @content);
            $content = join("", $ul_with_style, $li_with_style, $content, "</UL>")
                if $content;
            print p({-style => "margin-top: 1em; margin-bottom: 0em;"},
                    join("<BR>", @headers) . $content) . "\n";
        }
    }

    print qq{<script src="http://fit.genomics.lbl.gov/d3js/d3.min.js"></script>
             <script src="http://fit.genomics.lbl.gov/images/fitblast.js"></script>
             <H3><A title="Fitness BLAST searches for similarity to bacterial proteins that have mutant phenotypes" HREF="http://fit.genomics.lbl.gov/" NAME="#fitness">Fitness Blast</A></H3>
             <P><DIV ID="fitblast_short"></DIV></P>
             <script>
             var server_root = "http://fit.genomics.lbl.gov/";
             var seq = "$seq";
             fitblast_load_short("fitblast_short", server_root, seq);
             </script>
    } unless $more_subjectId;

    my @pieces = $seq =~ /.{1,60}/g;
    if (! $more_subjectId) {
      print h3("Query Sequence"),
        p({-style => "font-family: monospace;"}, small(join(br(), ">$def", @pieces))),
      }
    print h3(a({-href => "litSearch.cgi"}, "New Search")),
      $documentation,
        end_html;
}

sub fail($) {
    my ($notice) = @_;
    print
        p($notice),
        p(a({-href => "litSearch.cgi"}, "New search")),
        end_html;
    exit(0);
}

sub simstring($$$$$$$$$$$$$) {
    my ($qLen, $sLen, $queryStart,$queryEnd,$subjectStart,$subjectEnd,$percIdentity,$eVal,$bitscore,
        $def1, $def2, $seq1, $acc2) = @_;
    $percIdentity = sprintf("%.0f", $percIdentity);
    # the minimum of coverage either way
    my $cov = ($queryEnd-$queryStart+1) / ($qLen > $sLen ? $qLen : $sLen);
    my $percentCov = sprintf("%.0f", 100 * $cov);
    my $title ="$queryStart:$queryEnd/$qLen of query is similar to $subjectStart:$subjectEnd/$sLen of hit (E = $eVal, $bitscore bits)";
    return "(" .
        a({ -title => $title,
            -href => "showAlign.cgi?def1=$def1&def2=$def2&seq1=$seq1&acc2=$acc2" },
          "$percIdentity% identity, $percentCov% coverage")
        . ")";
}

# The entry will include:
# showName, URL, priority (for choosing what to show first), subjectId, desc, organism, protein_length, source,
# and other entries that depend on the type -- either papers for a list of GenePaper/PaperAccess items,
# or pmIds (a list of pubmed identifiers)
sub SubjectToGene($) {
  my ($subjectId) = @_;
  if ($subjectId =~ m/^gnl\|ECOLI\|(.*)$/) {
    my $protein_id = $1;
    my $gene = $dbh->selectrow_hashref("SELECT * FROM EcoCyc WHERE protein_id = ?", {}, $protein_id);
    die "Unrecognized subject $subjectId" unless defined $gene;
    $gene->{subjectId} = $subjectId;
    $gene->{protein_id} = $protein_id;
    $gene->{source} = "EcoCyc";
    $gene->{URL} = "http://ecocyc.org/gene?orgid=ECOLI&id=$protein_id";
    my @ids = ( $gene->{protein_name}, $gene->{bnumber} );
    @ids = grep { $_ ne "" } @ids;
    $gene->{showName} = join(" / ", @ids) || $protein_id;
    $gene->{priority} = 1;
    $gene->{organism} = "Escherichia coli K-12";
    $gene->{pmIds} = $dbh->selectcol_arrayref("SELECT pmId FROM EcoCycToPubMed WHERE protein_id = ?",
                                              {}, $protein_id);
    return $gene;
  } else {
    # Check in UniProt before checking in Gene, but UniProt items may show up in Gene as well.
    my $gene = $dbh->selectrow_hashref("SELECT * FROM UniProt WHERE acc = ?", {}, $subjectId);
    if (defined $gene) {
      $gene->{subjectId} = $subjectId;
      $gene->{priority} = 2;
      $gene->{source} = "SwissProt";
      $gene->{URL} = "http://www.uniprot.org/uniprot/$subjectId";
      $gene->{showName} = $gene->{acc};
      my @comments = split /_:::_/, $gene->{comment};
      @comments = map { s/[;. ]+$//; $_; } @comments;
      @comments = grep m/^SUBUNIT|FUNCTION|COFACTOR|CATALYTIC|ENZYME|DISRUPTION/, @comments;
      my $comment = join("<BR>\n", @comments);
      my @pmIds = $comment =~ m!{ECO:0000269[|]PubMed:(\d+)}!;
      $comment =~ s!{ECO:[A-Za-z0-9_:,.| -]+}!!g;
      $gene->{comment} = $comment;
      $gene->{pmIds} = \@pmIds;
    } else { # look in Gene table
      $gene = $dbh->selectrow_hashref("SELECT * FROM Gene WHERE geneId = ?", {}, $subjectId);
      die "Unrecognized gene $subjectId" unless defined $gene;
      $gene->{subjectId} = $subjectId;
      $gene->{priority} = 3;
      if ($subjectId =~ m/^VIMSS(\d+)$/) {
        my $locusId = $1;
        $gene->{source} = "MicrobesOnline";
        $gene->{URL} = "http://www.microbesonline.org/cgi-bin/fetchLocus.cgi?locus=$locusId";
        $gene->{desc} = "no description" if $gene->{desc} eq "";
      } elsif ($subjectId =~ m/^[A-Z]+_[0-9]+[.]\d+$/) { # refseq
        $gene->{URL} = "http://www.ncbi.nlm.nih.gov/protein/$subjectId";
        $gene->{source} = "RefSeq";
      } elsif ($subjectId =~ m/^[A-Z][A-Z0-9]+$/) { # SwissProt/TREMBL
        $gene->{URL} = "http://www.uniprot.org/uniprot/$subjectId";
        $gene->{source} = "SwissProt/TReMBL";
      } else {
        die "Cannot build a URL for subject $subjectId";
      }
    }
    # add papers, even if from UniProt
    my $papers = $dbh->selectall_arrayref(qq{ SELECT DISTINCT * FROM GenePaper
                                              LEFT JOIN PaperAccess USING (pmcId,pmId)
                                              WHERE geneId = ?
                                              ORDER BY year DESC },
                                          { Slice => {} }, $subjectId);
    $gene->{papers} = $papers;
    if (!defined $gene->{showName}) { # already set for UniProt genes
      my @terms = map { $_->{queryTerm} } @$papers;
      my %terms = map { $_ => 1 } @terms;
      @terms = sort keys %terms;
      $gene->{showName} = join(", ", @terms) if !defined $gene->{showName};
    }

    return $gene;
  }
}

sub VIMSSToQuery($) {
  my ($locusId) = @_;
  die unless defined $locusId;
  $locusId =~ s/^VIMSS//i;
  $locusId =~ m/^\d+$/ || die "Invalid locusId argument";
  my $mo_dbh = DBI->connect('DBI:mysql:genomics:pub.microbesonline.org', "guest", "guest")
    || die $DBI::errstr;
  my ($aaseq) = $mo_dbh->selectrow_array( qq{SELECT sequence FROM Locus JOIN AASeq USING (locusId,version)
                                             WHERE locusId = ? AND priority=1 },
                                          {}, $locusId);
  die "Unknown VIMSS id $locusId" unless defined $aaseq;
  return ">VIMSS$locusId\n$aaseq\n";
}
