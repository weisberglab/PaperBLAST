#!/usr/bin/perl -w
# View pathway reconstructions

# Optional parameters:
# orgs -- either an orgId as in FetchAssembly or a multi-organism directory
# set -- which group of pathways
# orgId -- which genome
# path -- which pathway
# showdef -- show the pathway definition
# step -- which step in that pathway
# locusId -- which candidate gene for that step
# gdb -- which genome database to search in
# gquery -- an organism name to search for
# findgene -- a search term for finding proteins
# file -- uploaded fasta file (used to create orgs)
#	(This usually leads to running the analysis, or showing
#	the overview page)
#
# Modes of this viewer:
# If gdb and gquery are set, search for relevant genomes
# Otherwise, if orgs is missing, either build it from gdb and gid,
#	or, show the front page
# Otherwise, require orgs (set defaults to "aa")
# If the analysis has not been run yet, it tries to run the analysis
#	If the orgs directory does not exist, it tries to fetch the genome first
# If the analysis was started recently, it waits
# Otherwise, the analysis exists:
# No other arguments -- list the genomes and pathways
#	(if there is just one organism, shows that overview instead)
# gaps -- list the gaps for all organisms or, if orgId is set, for 1 organism
# orgId -- overview of the organism
# path -- overview of the pathway across organisms
#	(if there is just one organism, shows that organism/pathway page instead)
# path & showdef -- detailed pathway definition (mostly, show the .steps file verbatim)
# orgId & path -- the pathway in the organism, with lists of rules and top candidates for each step
# orgId & path & step -- all candidates for the step, and the detailed definition of the step
# orgId & locusId -- show information about the gene, which step it is a candidate for, etc.
# orgId & path & step & locusId -- show relevant alignments
# orgId & findgene -- find genes matching

use strict;
use CGI qw(:standard Vars start_ul);
use CGI::Carp qw(warningsToBrowser fatalsToBrowser);
use HTML::Entities;
use IO::Handle qw{autoflush};
use lib "../lib";
use Steps;
use pbutils;
use pbweb qw{start_page};
use FetchAssembly qw{CacheAssembly AASeqToAssembly GetMatchingAssemblies GetMaxNAssemblies};
use File::stat;

sub ScoreToStyle($);
sub ScoreToLabel($);
sub ShowScoreShort($);
sub HMMToURL($);
sub GeneURL($$); # orgId (that is in %orgs), locusId
sub RuleToScore($);
sub ReadSumCand($$);
sub SumCandToHash($);
sub ReadSumSteps($);
sub OrgIdToURL($);
sub OrgToAssembly($);
sub Finish(); # show "About GapMind" and exit
sub CandToOtherColumns($);
sub CuratedToLink($$);
sub ProcessUpload($);
sub ShowCandidatesForStep($$$$);
sub LoadStepObj($$);
sub GetStepsObj($$);
sub StepRowToCuratedComment($$);
sub StepRowToCurated($$);
sub ShowCuratedLong($);
sub LegendForColorCoding();
sub ShowWarnings($$$$);

my $tmpDir = "../tmp"; # for CacheAssembly
my %orgs = (); # orgId => hash including gdb, gid, genomeName
my $nCPU = 6;

# maximum size of posted data, in bytes
my $maxMB = 100;
$CGI::POST_MAX = $maxMB*1024*1024;
my $maxNSeqsK = 100;
my $maxNSeqs = $maxNSeqsK * 1000;
my $charsInId = "a-zA-Z90-9:_.-"; # only these characters are allowed in protein ids

{
  FetchAssembly::SetFitnessBrowserPath("../fbrowse_data");
  FetchAssembly::SetPrivDir("../private");

  my $set = param("set") || "aa";
  $set =~ m/^[a-zA-Z0-9._-]+$/ || die "Invalid set $set";
  my $stepPath = "../gaps/$set"; # with the *.step files and the $set.table file
  my $queryPath = "../tmp/path.$set"; # with the *.query files and other intermediate files
  foreach my $dir ($stepPath,$queryPath) {
    die "Invalid set $set: no $dir directory" unless -d $dir;
  }

  my @pathInfo = ReadTable("$stepPath/$set.table", ["pathwayId","desc"]);
  my ($setDescRow) = grep {$_->{pathwayId} eq "all"} @pathInfo;
  die "No info for all in $stepPath/$set.table" unless defined $setDescRow;
  my $setDesc = $setDescRow->{desc};
  @pathInfo = grep {$_->{pathwayId} ne "all"} @pathInfo;
  my %pathDesc = map { $_->{pathwayId} => $_->{desc} } @pathInfo;

  autoflush STDOUT 1; # show preliminary results
  my $banner = "GapMind for $setDesc";

  my @gdbs = ("NCBI", "IMG", "UniProt", "MicrobesOnline", "FitnessBrowser");
  my %gdb_labels1 = ("NCBI" => "NCBI assemblies",
                     "UniProt" => "UniProt proteomes",
                     "IMG" => "JGI/IMG genomes", "FitnessBrowser" => "Fitness Browser genomes",
                     "local" => "Uploaded proteome");
  my %gdb_labels = map { $_ => exists $gdb_labels1{$_} ? $gdb_labels1{$_} : "$_ genomes"} @gdbs;

  my $orgsSpec = param('orgs');
  $orgsSpec = param('gdb') . "__" . param('gid')
    if !defined $orgsSpec && param('gdb') && param('gid');

  if (defined param('file')) {
    # Process the upload file and set $orgsSpec
    my $upFile = param('file');
    my $error;
    my %up;
    if (ref $upFile) {
      my $fhUp = $upFile->handle || die "Not a file handle";
      %up = ProcessUpload($fhUp);
      $error = $up{error};
    } else {
      $error = "No upload file specified";
    }
    if ($error) {
      start_page('title' => 'Upload Error in GapMind',
                 'banner' => $banner,
                 'bannerURL' => "gapView.cgi");
      print p(HTML::Entities::encode($error));
      Finish();
    }
    # else
    $orgsSpec = $up{gdb} . "__" . $up{gid};
  }

  if (!defined $orgsSpec && param('gquery')) {
    # mode: Find genome
    my $gquery = param('gquery');
    my $gdb = param('gdb') || die "Must specify gdb with gquery";
    die "Unknown genome database: $gdb\n"
      if !exists $gdb_labels{$gdb};
    start_page('title' => "GapMind for $setDesc",
               'banner' => $banner,
               'bannerURL' => "gapView.cgi");
    print p("Searching", $gdb_labels{$gdb}, "for", "'" . $gquery . "'"), "\n";
    my @rows = GetMatchingAssemblies($gdb, $gquery);
    my $limit = GetMaxNAssemblies();
    if (@rows > 0) {
      my $desc = "Found " . scalar(@rows) . " assemblies";
      if (@rows == 1) {
        $desc = "Found 1 assembly";
      } elsif (@rows >= $limit) {
        $desc = "Found the first " . scalar(@rows) . " matching assemblies";
      }
      $desc .= ", please choose one" if @rows > 1;
      print p($desc . ":"), "\n";
      print start_form(-method => 'get', -action => 'gapView.cgi'),
        hidden(-name => 'gdb', -value => $gdb, -override => 1),
        hidden(-name => 'set', -value => $set, -override => 1);
      foreach my $row (@rows) {
        my $checked = @rows == 1 ? "CHECKED" : "";
        print qq{<INPUT type="radio" NAME="gid" VALUE="$row->{gid}" $checked />},
          a({ -href => $row->{URL} }, $row->{genomeName} ),
            " ", small("(" . $row->{gid} . ")"), br();
      }
      print p(submit(-name => "Analyze")),
            end_form;
      Finish();
    } else {
      print p("Sorry, no matching genomes were found.");
    }
    print p("Try", a({-href => "gapView.cgi?set=$set&gdb=$gdb"}, "another genome"));
    Finish();
  } elsif (!defined $orgsSpec) {
    # mode: Front page
    start_page('title' => "Mind gaps in $setDesc",
               'banner' => $banner,
               'bannerURL' => "gapView.cgi");
    print
      p("View 'gaps' in",
        a({-href => "gapView.cgi?set=$set&orgs=orgs35"}, "35 bacteria"),
        "that grow in minimal media, or choose a genome to analyze:"),
      start_form(-method => 'get', -action => "gapView.cgi", -autocomplete => 'on'),
      hidden(-name => 'set', -value => $set, -override => 1),
      p("Genome database to search:",
        popup_menu(-name => 'gdb', -values => \@gdbs, -labels => \%gdb_labels, -default => $gdbs[0])),
      p(textfield(-name => 'gquery', -value => '', -size => 50, -maxlength => 200)),
      p(small("Example:", a({-href => "gapView.cgi?gdb=NCBI&gquery=Desulfovibrio vulgaris"}, "Desulfovibrio vulgaris"))),
      p(submit(-name => "findgenome", -value => 'Find Genome')),
      end_form,
      start_form(-method => 'post', -action => "gapView.cgi", -autocomplete => 'on'),
      hidden(-name => 'set', -value => $set, -override => 1),
      p("Or upload a proteome in fasta format:",
        filefield(-name=>'file', -size=>40)),
      p(submit('Upload')),
      end_form;
    Finish();
  }

  $orgsSpec =~ m/^[a-zA-Z0-9._-]+$/ || die "Invalid orgs $orgsSpec";
  my $orgpre = "../tmp/$orgsSpec/orgs";
  my $sumpre = "../tmp/$orgsSpec/$set.sum";
  my $warningFile = "$sumpre.warn";

  my $alreadyBuilt = NewerThan("$sumpre.done", "$queryPath/date");

  # Wait up to 5 minutes for a previously running job to finish
  if (! $alreadyBuilt
      && -e "$sumpre.begin"
      && stat("$sumpre.begin")->mtime >= time() - 5*60) {
    # mode: The analysis is already running
    start_page('title' => 'Analysis in progress',
               'banner' => $banner,
               'bannerURL' => "gapView.cgi");
    print
      p("Analysis of $setDesc is already underway. Please check",
        a({-href => "gapView.cgi?orgs=$orgsSpec&set=$set"}, "here"),
        "in a few seconds");
      Finish();
  }

  unless ($alreadyBuilt) {
    # mode: Run the analysis
    start_page('title' => "Analyzing $setDesc",
               'banner' => $banner,
               'bannerURL' => "gapView.cgi");
    print "\n";
    unless (-e "$orgpre.org") {
      # Try to load the organism
      $orgsSpec =~ m/^([^_]+)__(.*)$/ || die "Invalid organism specifier $orgsSpec";
      my ($gdb,$gid) = ($1,$2);
      print p("Fetching assembly $gid from $gdb"), "\n";
      CacheAssembly($gdb, $gid, $tmpDir) || die;
      mkdir("$tmpDir/$orgsSpec");
      # buildorgs.pl creates $orgpre.org and $orgpre.faa and runs formatdb
      my @cmd = ("../bin/buildorgs.pl", "-out", $orgpre, "-orgs", $gdb.":".$gid);
      system(@cmd) == 0
        || die "command @cmd\nfailed with error: $!";
    }
    my @orgs = ReadOrgTable("$orgpre.org");
    die "No organisms for $orgpre.org" unless @orgs > 0;
    die "No such file: $orgpre.faa" unless -e "$orgpre.faa";
    my @qFiles = map { $queryPath . "/" . $_->{pathwayId} . ".query" } @pathInfo;
    foreach my $qFile (@qFiles) {
      die "No such file: $qFile" unless -e $qFile;
    }
    system("touch", "$sumpre.begin");
    unlink($warningFile);
    my $time = 15 * scalar(@orgs);
    print p("Analyzing $setDesc in", scalar(@orgs), "genomes. This should take around $time seconds."), "\n";
    my @cmds = ();
    push @cmds, ["../bin/gapsearch.pl", "-orgs", $orgpre, "-query", @qFiles,
                 "-nCPU", $nCPU, "-out", "$tmpDir/$orgsSpec/$set.hits"];
    push @cmds, ["../bin/gaprevsearch.pl", "-orgs", $orgpre,
                 "-hits", "$tmpDir/$orgsSpec/$set.hits",
                 "-nCPU", $nCPU,
                 "-curated", "$queryPath/curated.faa.udb",
                 "-out", "$tmpDir/$orgsSpec/$set.revhits"];
    my @pathList = map { $_->{pathwayId} } @pathInfo;
    push @cmds, ["../bin/gapsummary.pl",
                 "-pathways", @pathList,
                 "-orgs", $orgpre,
                 "-hits", "$tmpDir/$orgsSpec/$set.hits",
                 "-rev", "$tmpDir/$orgsSpec/$set.revhits",
                 "-out", "$tmpDir/$orgsSpec/$set.sum",
                 "-info", "$queryPath/curated.faa.info",
                 "-stepDir", $stepPath,
                 "-queryDir", $queryPath];
    push @cmds, ["touch", "$sumpre.done"];
    my %label = ('gapsearch.pl' => 'Searching for candidates for each step',
                 'gaprevsearch.pl' => 'Comparing candidates to other curated proteins',
                 'gapsummary.pl' => 'Scoring each candidate and pathway');
    foreach my $cmd (@cmds) {
      my $show = $cmd->[0]; $show =~ s!.*/!!;
      print p($label{$show})."\n" if exists $label{$show};
      system(@$cmd) == 0 || die "Command failed\n@$cmd\nError code: $!";
    }
    unlink("$sumpre.begin");
    print "</pre>\n",
      p("Analysis succeeded, please",
      a({-href => "gapView.cgi?orgs=$orgsSpec&set=$set"}, "view results")),
      end_html;
    exit(0);
  }

  #else -- viewing modes
  my @orgs = ReadOrgTable("$orgpre.org");
  die "No organisms for $orgpre.org" unless @orgs > 0;
  %orgs = map { $_->{orgId} => $_ } @orgs;
  my $faafile = "$orgpre.faa";
  die "No such file: $faafile" unless -e $faafile;

  # Make sure the warnings file is up to date
  unless (NewerThan($warningFile, "$stepPath/requires.tsv")) {
    system("../bin/checkGapRequirements.pl -org ../tmp/$orgsSpec > $warningFile.$$.tmp") == 0
      || die "checkGapRequirements.pl failed";
    rename("$warningFile.$$.tmp", $warningFile)
      || die "Failed to rename $warningFile.$$.tmp to $warningFile";
  }
  my @warn = ReadTable($warningFile,
                       qw{orgId pathway rule requiredPath requiredRule requiredStep not comment});

  my $pathSpec = param("path");
  $pathSpec = "" if !defined $pathSpec;
  die "Invalid path parameter $pathSpec"
    unless $pathSpec eq "" || $pathSpec =~ m/^[a-zA-Z0-9._-]+$/;
  my @path = (); # all pathways, or the one specified

  if ($pathSpec eq "") {
    @path = map { $_->{pathwayId} } @pathInfo;
  } else {
    die "Unknown pathway $pathSpec" unless exists $pathDesc{$pathSpec};
    die "Invalid path $pathSpec" unless $pathSpec =~ m/^[a-zA-Z0-9._'-]+$/;
  }

  my $orgId = param("orgId"); # the organism specified, or, ""
  $orgId = "" if !defined $orgId;
  if ($orgId ne "") {
    die "Unknown orgId $orgId" unless exists $orgs{$orgId};
  }
  $orgId = $orgs[0]{orgId} if @orgs == 1;

  my $step = param("step");
  $step = "" if !defined $step;
  if ($step ne "") {
    die "step specified without path specified" unless $pathSpec ne "";
    $step =~ m/^[a-zA-Z0-9._'"-]+$/ || die "Invalid step $step";
    my $st = GetStepsObj($stepPath, $pathSpec);
    die "Non-existent step $step" unless exists $st->{steps}{$step};
  }

  my $locusSpec = param("locusId");
  $locusSpec = "" if !defined $locusSpec;
  $locusSpec =~ m/^[$charsInId]*$/ || die "Invalid locus $locusSpec";

  my $findgene = param('findgene');
  $findgene = "" if !defined $findgene;
  my $findgeneShow = HTML::Entities::encode($findgene);

  my $title = $setDesc;
  $title = "Potential Gaps in $setDesc" if param('gaps');
  if ($locusSpec ne "") {
    $title = $step ne "" ? "Aligments for a candidate for $step" : "Protein $locusSpec";
  } elsif ($pathSpec ne "") {
    $title = $pathDesc{$pathSpec};
  }
  $title = "Finding step $step for $pathDesc{$pathSpec}"
    if $step ne "" && $orgId ne "" && $pathSpec ne "" && $locusSpec eq "";
  $title = "Searching for proteins"
    if $orgId ne "" && $findgene ne "";
  $title .= " in $orgs{$orgId}{genomeName}"
    if $orgId ne "";
  $title = "Definition of $pathDesc{$pathSpec}" if $pathSpec ne "" && param("showdef");
  my $nOrgs = scalar(@orgs);
  start_page('title' => $title,
             'banner' => $banner,
             'bannerURL' => "gapView.cgi");
  print "\n";

  my @curatedGaps = ReadTable("$stepPath/$set.curated.gaps.tsv",
                              qw{gdb gid pathway step class comment});
  @curatedGaps = grep { $_->{class} ne "" } @curatedGaps;
  my %curatedGaps = (); # gid => pathway => step => row; step may be ""
  foreach my $c (@curatedGaps) {
    die "Unknown pathway $c->{pathway}" unless exists $pathDesc{ $c->{pathway} };
    die "Duplicate row for $c->{gid} $c->{pathway} $c->{step}"
      if exists $curatedGaps{ $c->{gid} }{ $c->{pathway} }{ $c->{step} };
    $curatedGaps{ $c->{gid} }{ $c->{pathway} }{ $c->{step} } = $c;
  }

  my @orgsSorted = sort { $a->{genomeName} cmp $b->{genomeName} } @orgs;
  my @ruleScoreLabels = ("has a gap", "may have a gap", "all steps were found");

  my @links = ();     # a list of items to put inside li at the bottom
  if ($pathSpec ne "" && param("showdef")) {
    # mode: Show the definition of this pathway
    my $stfile = "$stepPath/$pathSpec.steps";
    open (my $fh, "<", $stfile) || die "No such file: $stfile\n";
    my @lines = <$fh>;
    close($fh) || die "Error reading $fh";
    print pre(join("",@lines)), "\n";
    push @links, a({-href => "$queryPath/$pathSpec.query"}, "Table of queries for $pathSpec")
      . " (tab-delimited)";
  } elsif (param('gaps')) {
    # mode: Overview of gaps, either for 1 organism or all organisms
    my @gaps = grep { ($_->{score} eq "" || $_->{score} < 2) && $_->{onBestPath} } ReadSumSteps($sumpre);
    @gaps = grep { $_->{orgId} eq $orgId } @gaps
      if $orgId ne "";
    @gaps = sort { $a->{pathway} cmp $b->{pathway}
                    || $a->{step} cmp $b->{step}
                    || $orgs{ $a->{orgId} }{genomeName} cmp $orgs{$b->{orgId} }{genomeName}} @gaps;
    if (@gaps == 0) {
      print p("Each pathway in",
              a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId" },
                $orgs{$orgId}{genomeName}),
              "has a high-confidence path");
    } else {
      my %pathSteps = (); # pathId to steps object (if loaded already)
      my @cand = ReadSumCand($sumpre, "");
      @cand = grep { $_->{orgId} eq $orgId } @cand
        if $orgId ne "";
      my $candHash = SumCandToHash(\@cand);
      my $nLo = scalar(grep {$_->{score} eq "0" || $_->{score} eq ""} @gaps);
      my $nMed = scalar(grep {$_->{score} eq "1"} @gaps);
      my $nTot = scalar(@gaps);
      die unless $nTot == $nLo + $nMed;
      my $totals = "Found $nLo low-confidence and $nMed medium-confidence steps on the best paths for "
        . scalar(@pathInfo) . " pathways";
      $totals .= " x " . scalar(@orgs) . " genomes" if $orgId eq "";
      my $nCurated = 0;
      foreach  my $row (@gaps) {
        $nCurated++ if StepRowToCurated($row, \%curatedGaps);
      }
      $totals .= ".";
      $totals .= " $nCurated of $nTot gaps have been manually classified."
        if $nCurated > 0;
      print p($totals);
      my @th = qw{Pathway Step Organism Best-candidate 2nd-candidate};
      map s/-/ /g, @th;
      push @th, "Class of gap" if $nCurated > 0;
      my @tr = ();
      push @tr, Tr(th({-valign => "top"}, \@th));
      foreach my $row (@gaps) {
        my ($show1, $show2) = ShowCandidatesForStep($orgsSpec, $set, $row, $candHash);
        my $p = $row->{pathway};
        my $s = $row->{step};
        my $o = $row->{orgId};
        my @td = ( a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$o&path=$p",
                       -title => $pathDesc{$p},
                       -style => ScoreToStyle($row->{score}) }, $p),
                   a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$o&path=$p&step=$s",
                       -title => ScoreToLabel($row->{score}),
                       -style => ScoreToStyle($row->{score}) },
                     "$s: " . GetStepsObj($stepPath, $p)->{steps}{$s}{desc}),
                   a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$o" },
                     $orgs{$o}{genomeName}),
                   $show1, $show2 );
        push @td, StepRowToCuratedComment($row, \%curatedGaps)
          if $nCurated > 0;
        push @tr, Tr(td({-valign => "top" }, \@td));
      }
      print table({-cellpadding=>2, -cellspacing=>0, -border=>1}, @tr), "\n";
      print LegendForColorCoding();
      ShowWarnings(\@warn, $orgsSpec, $set, $orgId);
    }
  } elsif ($orgId eq "" && $pathSpec eq "") {
    # mode: List pathways & genomes
    print p(scalar(@path), "pathways");
    print start_ul;
    foreach my $path (@path) {
      print li(a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&path=$path" },
                 $pathDesc{$path}));
    }
    print end_ul, "\n";
    # list genomes
    print p(scalar(@orgsSorted), "genomes"), "\n";
    print start_ul;
    foreach my $org (@orgsSorted) {
      my $orgId = $org->{orgId};
      my $URL = "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId";
      $URL .= "&path=$pathSpec" if @path == 1;
      print li(a({ -href => $URL }, $org->{genomeName} ));
    }
    print end_ul, "\n";
  } elsif ($orgId eq "" && $pathSpec ne "") {
    # mode: Overview of this pathway across organisms
    print p("Analysis of pathway $pathSpec in", scalar(@orgs), "genomes"), "\n";
    my @sumRules = ReadTable("$sumpre.rules", qw{orgId gdb gid pathway rule score nHi nMed nLo expandedPath});
    @sumRules = grep { $_->{pathway} eq $pathSpec && $_->{rule} eq "all" } @sumRules;
    my %orgAll = map { $_->{orgId} => $_ } @sumRules;
    my @sumSteps = ReadSumSteps($sumpre);
    @sumSteps = grep { $_->{pathway} eq $pathSpec} @sumSteps;
    my %orgStep = ();           # orgId => step => row from sum.steps
    foreach my $row (@sumSteps) {
      $orgStep{$row->{orgId}}{$row->{step}} = $row;
    }
    my $st = GetStepsObj($stepPath, $pathSpec);
    my $steps = $st->{steps};
    my @tr = ();
    my @th = qw{Genome Best-path};
    map s/-/ /, @th;
    push @tr, Tr(th({-valign => "top"}, \@th));
    foreach my $org (@orgsSorted) {
      my $orgId = $org->{orgId};
      my $all = $orgAll{$orgId} || die "No all line for $orgId and $pathSpec\n";
      my @show = ();
      foreach my $step (split / /, $all->{expandedPath}) {
        my $score = exists $orgStep{$orgId}{$step} ? $orgStep{$orgId}{$step}{score} : 0;
        my $stepObj = $orgStep{$orgId}{$step} || die;
        my $title = $steps->{$step}{desc};
        my $id = $stepObj->{sysName} || $stepObj->{locusId} || "";
        $title .= " $id" if $id ne "";
        my $c = StepRowToCurated($stepObj, \%curatedGaps);
        if ($c) {
          $title .= " (" . $c->{class} . " gap)";
        } else {
          $title .= " (" . ScoreToLabel($score) . ")";
        }
        push @show, a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$pathSpec&step=$step",
                        -style => ScoreToStyle($score), -title => $title },
                      $step);
      }
      my $score = RuleToScore($all);
      push @tr, Tr(td({-valign => "top"},
                      [ a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&path=$pathSpec&orgId=$orgId",
                            -style => ScoreToStyle($score),
                            -title => "$pathSpec $ruleScoreLabels[$score]" },
                          $orgs{$orgId}{genomeName}),
                        join(", ", @show) ]));
    }
    print table({-cellpadding=>2, -cellspacing=>0, -border=>1}, @tr), "\n";
    print LegendForColorCoding();
    my @warnShow = grep { $_->{pathway} eq $pathSpec } @warn;
    ShowWarnings(\@warnShow, $orgsSpec, $set, "");
  } elsif ($orgId ne "" && $findgene ne "") {
    # mode: Search for a gene
    print p(qq{Searching for "$findgeneShow" in}, $orgs{$orgId}{genomeName}), "\n";
    my $assembly = OrgToAssembly($orgId);
    my $regexp = quotemeta($findgene);
    $regexp =~ s/\\%/.*/g;
    my @hits = (); # each is a list of [locusId, desc]
    if (exists $assembly->{features}) {
      foreach my $row (@{ $assembly->{features} }) {
        next unless $row->{class} eq "with_protein";
        next unless $row->{name} =~ m/$regexp/i
          || $row->{locus_tag} =~ m/^$regexp/i
          || (exists $assembly->{oldid}{$row->{locus_tag}} && $assembly->{oldid}{$row->{locus_tag}} =~ m/^$regexp/i);
        my $id = $row->{product_accession} || $row->{"non-redundant_refseq"};
        die "Invalid identifier $id in feature file\n"
          unless defined $id && $id ne "";
        my $desc = $row->{name};
        my @moreids = ();
        if ($row->{locus_tag}) {
          push @moreids, $row->{locus_tag};
          push @moreids, $assembly->{oldid}{$row->{locus_tag}}
            if exists $assembly->{oldid}{$row->{locus_tag}};
        }
        push @hits, [ $id, join(" ", @moreids, $desc) ];
      }
    } else {
      die "No faa file for this assembly\n" unless exists $assembly->{faafile};
      open(my $fhA, "<", $assembly->{faafile}) || die "Cannot read $assembly->{faafile}";
      my $state = {};
      while (my ($header, undef) = ReadFastaEntry($fhA, $state)) {
        if ($header =~ m/$regexp/i) {
          my @pieces = split / /, $header;
          my $id = shift @pieces;
          die "Blank header in fasta file" unless defined $id && $id ne "";
          push @hits, [ $id, join(" ", @pieces) ];
        }
      }
      close($fhA) || die "Error reading $assembly->{faafile}";
    }
    if (@hits == 0) {
      print p("No matching proteins were found");
    } else {
      my @cand = ReadSumCand($sumpre,"");
      my %locusNCand = ();
      foreach my $row (@cand) {
        $locusNCand{$row->{locusId}}++;
      }
      foreach my $row (@hits) {
        my ($id, $desc) = @$row;
        $desc .= small(" (candidate for", $locusNCand{$id}, "steps)")
          if exists $locusNCand{$id};
        print p(a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&locusId=$id"}, $id),
                $desc)."\n";
      }
    }
  } elsif ($orgId ne "" && $pathSpec eq "" && $locusSpec eq "") {
    # mode: Overview of pathways for this organism
    my @hr = ("Pathway", span({-title=>"Best path"}, "Steps"));
    my @tr = ();
    push @tr, th({-valign => "top"}, \@hr);
    my @sumRules = ReadTable("$sumpre.rules", qw{orgId gdb gid pathway rule score nHi nMed nLo expandedPath});
    my @all = grep { $_->{orgId} eq $orgId && $_->{rule} eq "all" } @sumRules;
    my %all = map { $_->{pathway} => $_ } @all;
    my @sumSteps = ReadSumSteps($sumpre);
    @sumSteps = grep { $_->{orgId} eq $orgId } @sumSteps;
    my %sumSteps = (); # pathway => step => summary
    foreach my $st (@sumSteps){
      die if exists $sumSteps{$st->{pathway}}{$st->{step}};
      $sumSteps{$st->{pathway}}{$st->{step}} = $st;
    }
    foreach my $path (@path) {
      my $all = $all{$path} || die "Missing result for rule = all and orgId = $orgId in $sumpre.rules\n"
        unless @all == 1;
      my @show = ();

      my $st = GetStepsObj($stepPath, $path);
      my $steps = $st->{steps};
      foreach my $step (split / /, $all->{expandedPath}) {
        die "Unknown step $step for $path\n" unless exists $steps->{$step};
        my $stepObj = $sumSteps{$path}{$step};
        my $score = $stepObj->{score};
        my $title = $steps->{$step}{desc};
        my $id = $stepObj->{sysName} || $stepObj->{locusId} || "";
        $title .= " $id" if $id;
        my $c = StepRowToCurated($stepObj, \%curatedGaps);
        if ($c) {
          $title .= " (" . $c->{class} . " gap)";
        } else {
          $title .= " " . ScoreToLabel($score);
        }
        push @show, a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$path&step=$step",
                        -style => ScoreToStyle($score), -title => $title },
                      $step);
      }
      my $pathScore = RuleToScore($all);
      push @tr, Tr({-valign => "top"},
                   td([a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$path",
                           -style => ScoreToStyle($pathScore),
                           -title => $pathDesc{$path } . " - " . $ruleScoreLabels[$pathScore] }, $path),
                       join(", ", @show)]));
    }
    print table({-cellpadding=>2, -cellspacing=>0, -border=>1}, @tr), "\n";
    print LegendForColorCoding();
    ShowWarnings(\@warn, $orgsSpec, $set, $orgId);
  } elsif ($orgId ne "" && $pathSpec ne "" && $step eq "" && $locusSpec eq "") {
    # mode: Overview of this pathway in this organism
    # First the rules, then all of the steps, then the dependency warnings
    my $st = GetStepsObj($stepPath, $pathSpec);
    my $steps = $st->{steps};
    my $rules = $st->{rules};
    my @sumRules = ReadTable("$sumpre.rules", qw{orgId gdb gid pathway rule score nHi nMed nLo expandedPath});
    @sumRules = grep { $_->{orgId} eq $orgId && $_->{pathway} eq $pathSpec } @sumRules;
    my %sumRules = map { $_->{rule} => $_ } @sumRules;
    my @sumSteps = ReadSumSteps($sumpre);
    @sumSteps = grep { $_->{orgId} eq $orgId && $_->{pathway} eq $pathSpec } @sumSteps;
    my %sumSteps = map { $_->{step} => $_ } @sumSteps;
    my @cand = ReadSumCand($sumpre, $pathSpec);
    @cand = grep { $_->{orgId} eq $orgId } @cand;
    my $candHash = SumCandToHash(\@cand);

    my $gid = $orgs{$orgId}{gid};
    my $curatedGapTop = exists $curatedGaps{$gid}{$pathSpec}{""} ?
      $curatedGaps{$gid}{$pathSpec}{""} : undef;
    print ShowCuratedLong($curatedGapTop);

    print h3(scalar(@sumRules), "rules"), "\n";

    print start_ul;
    foreach my $rule (reverse @sumRules) {
      my $hasSubRule = 0;
      my @stepList = split / /, $rule->{expandedPath};
      print li($rule->{rule});
      print start_ul;
      my $or = "";
      foreach my $list (@{ $rules->{ $rule->{rule} } }) {
        my @parts = ();
        foreach my $part (@$list) {
          if (exists $steps->{$part}) {
            my $score = exists $sumSteps{$part} ? $sumSteps{$part}{score} : 0;
            my $title = $steps->{$part}{desc};
            my $partObj = exists $sumSteps{$part} ? $sumSteps{$part} : {};
            my $id = $partObj->{sysName} || $partObj->{locusId} || "";
            $title .= " $id" if $id ne "";
            my $curatedGap = $curatedGaps{$gid}{$pathSpec}{$part}
              if exists $curatedGaps{$gid}{$pathSpec}{$part}; # do not look at ""
            if ($curatedGap) {
              $title .= " (" . $curatedGap->{class} . " gap)";
            } else {
              $title .= " (" . ScoreToLabel($score) . ")";
            }
            push @parts, a({ -style => ScoreToStyle($score), -title => $title,
                             -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$pathSpec&step=$part" },
                           $part);
          } elsif (exists $rules->{$part}) {
            my $score = RuleToScore($sumRules{$part});
            push @parts, span({ -style => ScoreToStyle($score), -title => "see rule for $part below" }, $part);
            $hasSubRule = 1;
          } else {
            die "Unknown part $part";
          }
        }
        print li("${or}steps: " . join(", ", @parts));
        $or = "or ";
      }
      my @bestparts = ();
      foreach my $step (@stepList) {
        my $stepDef = $steps->{$step} || die "Invalid step $step";
        my $stepS = exists $sumSteps{$step} ? $sumSteps{$step} : {};
        my $score = $stepS->{score} || 0;
        my $id = $stepS->{sysName} || $stepS->{locusId} || "";
        my $title = $stepDef->{desc};
        $title .= " $id" if $id ne "";
        my $curatedGap = $curatedGaps{$gid}{$pathSpec}{$step}
          if exists $curatedGaps{$gid}{$pathSpec}{$step}; # do not look at ""
        if ($curatedGap) {
          $title .= " (" . $curatedGap->{class} . " gap)";
        } else {
          $title .= " (" . ScoreToLabel($score) . ")";
        }
        push @bestparts, a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$pathSpec&step=$step",
                         -style => ScoreToStyle($score),
                         -title => $title },
                       $step);
      }
      print li("best-scoring path:", @bestparts) if $hasSubRule || @{ $rules->{ $rule->{rule} } } > 1;
      print end_ul, "\n";
    }
    print end_ul, "\n";
    my @stepsSorted = sort { $a->{i} <=> $b->{i} } (values %$steps);
    my @stepWithCand = grep { $_->{locusId} ne "" } @sumSteps;
    print h3(scalar(@stepsSorted) . " steps (" . scalar(@stepWithCand) . " with candidates)"), "\n";

    my $nCurated = 0;
    foreach  my $row (@sumSteps) {
      $nCurated++ if $row->{score} ne "2"
        && $row->{onBestPath}
        && StepRowToCurated($row, \%curatedGaps);
    }

    my @tr = ();
    my @header = qw{Step Description Best-candidate 2nd-candidate};
    foreach (@header) {
      s/-/ /;
    }
    push @header, "Class of gap" if $nCurated > 0;
    push @tr, Tr(th(\@header));
    # For each step, show the step name and description, the best candidate (if any), and the 2nd best candidate(s) if any
    foreach my $stepS (@stepsSorted) {
      my $step = $stepS->{name};
      die "invalid step $step" unless exists $steps->{$step};
      my ($show1, $show2) = ShowCandidatesForStep($orgsSpec, $set, $sumSteps{$step}, $candHash);
      my @td = ( a({-href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$pathSpec&step=$step"}, $step),
                 $stepS->{desc},
                 $show1, $show2 );
      push @td, StepRowToCuratedComment($sumSteps{$step}, \%curatedGaps)
        if $nCurated > 0;
      push @tr, Tr(td({-valign => "top" }, \@td));
    }
    print table({-cellpadding=>2, -cellspacing=>0, -border=>1}, @tr), "\n";
    print LegendForColorCoding();
    my @warnShow = grep { $_->{pathway} eq $pathSpec && $_->{orgId} eq $orgId } @warn;
    ShowWarnings(\@warnShow, $orgsSpec, $set, $orgId);
  } elsif ($orgId ne "" && $pathSpec ne "" && $step ne "" && $locusSpec eq "") {
    # mode: Overview of this step in this organism
    my $st = GetStepsObj($stepPath, $pathSpec);
    my $steps = $st->{steps};
    my @sumSteps = ReadSumSteps($sumpre);
    @sumSteps = grep { $_->{pathway} eq $pathSpec && $_->{orgId} eq $orgId && $_->{step} eq $step } @sumSteps;
    die unless @sumSteps == 1;
    my ($stepObj) = @sumSteps;

    my $curatedGap = StepRowToCurated($stepObj, \%curatedGaps);
    print ShowCuratedLong($curatedGap) if $stepObj->{score} ne "2" && $curatedGap;

    my @cand = ReadSumCand($sumpre,$pathSpec);
    @cand = grep { $_->{orgId} eq $orgId && $_->{step} eq $step } @cand;
    if (@cand == 0) {
      print h3("No candidates for $step: $steps->{$step}{desc}"), "\n";
    } else {
      print h3(scalar(@cand), "candidates for $step:", $steps->{$step}{desc}), "\n";

      my @header = qw{Score Gene Description Similar-to Id. Cov. Bits  Other-hit Other-id. Other-bits};
      $header[-1] = span({-title => "A characterized protein that is similar to the gene but is not associated with step $step"},
                         $header[-1]);
      foreach (@header) {
        s/-/ /;
      }
      my @tr = Tr(th({-valign => "bottom"}, \@header));
      foreach my $cand (@cand) {
        # potentially make two rows, one for BLAST and one for HMM
        my $id = a({-href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&locusId=".$cand->{locusId} },
                   $cand->{sysName} || $cand->{locusId} );
        my $desc = HTML::Entities::encode( $cand->{desc} );
        # HMM hits are based on the 1st ORF only so ignore the split when showing the HMM part
        my $id1 = $id;
        my $desc1 = $desc;
        if ($cand->{locusId2}) { # (this should only happen for BLAST hits)
          $id .= "; " . a({-href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&locusId=".$cand->{locusId2} },
                          $cand->{sysName2} || $cand->{locusId2} );
          $desc .= "; " . HTML::Entities::encode( $cand->{desc2} );
        }
        my ($linkOther, $otherIdentity, $otherBits) = CandToOtherColumns($cand);

        if ($cand->{blastScore} ne "") {
          push @tr, Tr(td({-valign => "top"},
                          [ ShowScoreShort($cand->{blastScore}),
                            $id, $desc,
                            CuratedToLink($cand->{curatedIds}, $cand->{curatedDesc}),
                            int(0.5 + $cand->{identity})."%",
                            a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$pathSpec&step=$step&locusId=$cand->{locusId}",
                                -title => "View alignments" },
                              int(0.5 + 100 * $cand->{blastCoverage})."%"),
                            $cand->{blastBits},
                            $linkOther, $otherIdentity, $otherBits ]));
        }

        if ($cand->{hmmScore} ne "") {
          my $hmmURL = HMMToURL($cand->{hmmId});
          push @tr, Tr(td({ -valign => "top" },
                          [ ShowScoreShort($cand->{hmmScore}), $id1, $desc1,
                            a({-href => $hmmURL, }, $cand->{hmmDesc}, "(". $cand->{hmmId} . ")"),
                            "",
                            a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$pathSpec&step=$step&locusId=$cand->{locusId}",
                                -title => "View alignments" },
                              int(0.5 + 100 * $cand->{hmmCoverage})."%"),
                            $cand->{hmmBits},
                            $linkOther, $otherIdentity, $otherBits ]));
        }
      }
      print table({-cellpadding=>2, -cellspacing=>0, -border=>1}, @tr), "\n";
      print LegendForColorCoding();
    }
    print h3("Definition of step $step"), "\n";
    print start_ul();
    foreach my $search (@{ $steps->{$step}{search} }) {
      my ($type,$value) = @$search;
      my $show;
      if ($type eq "EC") {
        my $URL = "http://papers.genomics.lbl.gov/cgi-bin/genomeSearch.cgi?gdb=" . $orgs{$orgId}{gdb}
          . "&gid=" . $orgs{$orgId}{gid}
            . "&query=$value&word=1";
        $show = "Curated proteins or TIGRFams with EC " . a({-href => $URL, -title => "Run Curated BLAST"}, $value);
      } elsif ($type eq "hmm") {
        $show = "HMM " . a({-href => HMMToURL($value) }, $value);
      } elsif ($type eq "term") {
        my $URL = "http://papers.genomics.lbl.gov/cgi-bin/genomeSearch.cgi?gdb=" . $orgs{$orgId}{gdb}
          . "&gid=" . $orgs{$orgId}{gid}
            . "&word=1"
              . "&query=" . encode_entities($value);
        $show = "Curated proteins matching " . a({-href => $URL, -title => "Run Curated BLAST"}, $value);
      } elsif ($type eq "curated") {
        my $URL = "http://papers.genomics.lbl.gov/cgi-bin/litSearch.cgi?query=".$value;
        my $show_id = $value; $show_id =~ s/^.*://;
        $show = "Curated sequence " . a({-href => $URL, -title => "View in PaperBLAST"}, $show_id);
      } elsif ($type eq "uniprot") {
        my $URL = "https://www.uniprot.org/uniprot/".$value;
        $show = "UniProt sequence " . a({-href => $URL, -title => "View in UniProt"}, $value);
      } elsif ($type eq "ignore_other") {
        my $URL = "http://papers.genomics.lbl.gov/cgi-bin/curatedSearch.cgi?word=1"
          . "&query=" . encode_entities($value);
        $show = "Ignore hits to items matching "
          . a({-href => $URL}, $value)
            . " when looking for 'other' hits";
      } elsif ($type eq "ignore") {
        my $URL = "http://papers.genomics.lbl.gov/cgi-bin/litSearch.cgi?query=$value";
        my $showId = $value; $showId =~ s/^.*://;
        $show = "Ignore hits to "
          . a({-href => $URL, -title => "View in PaperBLAST"}, $showId)
            . " when looking for 'other' hits";
      }
      print li($show);
    }
    print end_ul(), "\n";
  } elsif ($orgId ne "" && $step eq "" && $locusSpec ne "") {
    # mode: Show a gene
    # First fetch its header and sequence
    my $tmp = "/tmp/gapView.$locusSpec.$$";
    my $faaCand = "$tmp.genome.faa";
    FetchSeqs("../bin/blast", $faafile, [$orgId.":".$locusSpec], $faaCand);
    my %fasta = ReadFastaDesc($faaCand);
    unlink($faaCand);
    my $descs = $fasta{desc};
    my $seqs = $fasta{seq};
    die unless scalar(keys %$seqs) == 1 && scalar(keys %$descs) == 1;
    my ($desc) = values %$descs;
    my ($seq) = values %$seqs;
    print p("Annotation:", $desc);
    print p("Length:", length($seq), "amino acids");
    print p("Source:", $orgs{$orgId}{gid}, "in", $orgs{$orgId}{gdb});

    my @cand = ReadSumCand($sumpre,"");
    @cand = grep { $_->{locusId} eq $locusSpec || $_->{locusId2} eq $locusSpec} @cand;
    if (@cand == 0) {
      print p("Not a candidate for any step in $setDesc"),"\n";
    } else {
      print h3("Candidate for", scalar(@cand), "steps in $setDesc");
      my @header = qw{Pathway Step Score Similar-to Id. Cov. Bits Other-hit Other-id. Other-bits};
      foreach (@header) { s/-/ /; }
      my @tr = Tr(th({-valign => "bottom"}, \@header));
      foreach my $cand (@cand) {
        # potentially make two rows, one for BLAST and one for HMM
        my ($linkOther, $otherIdentity, $otherBits) = CandToOtherColumns($cand);
        my $pathLink = a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$cand->{pathway}" },
                         $pathDesc{ $cand->{pathway} });
        my $stepObj = GetStepsObj($stepPath, $cand->{pathway});
        die "Non-existent step $step" unless exists $stepObj->{steps}{ $cand->{step} };
        my $stepLink = a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$cand->{pathway}&step=$cand->{step}",
                           -title => $stepObj->{steps}{ $cand->{step} }{desc} },
                         $cand->{step} );
        if ($cand->{blastScore} ne "") {
          my $asterisk = "";
          $asterisk = a({ -title => "Split hit"}, "*") if $cand->{locusId2};
          push @tr, Tr(td({-valign => "top"},
                          [ $pathLink, $stepLink,
                            ShowScoreShort($cand->{blastScore}),
                            CuratedToLink($cand->{curatedIds}, $cand->{curatedDesc}),
                            int(0.5 + $cand->{identity})."%",
                            a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$cand->{pathway}&step=$cand->{step}&locusId=$locusSpec",
                                -title => "View alignments" },
                              int(0.5 + 100 * $cand->{blastCoverage})."%") . $asterisk,
                            $cand->{blastBits},
                            $linkOther, $otherIdentity, $otherBits ]));
        }
        if ($cand->{hmmScore} ne "") {
          my $hmmURL = HMMToURL($cand->{hmmId});
          push @tr, Tr(td{-valign => "top"},
                       [ $pathLink, $stepLink,
                         ShowScoreShort($cand->{hmmScore}),
                         a({-href => $hmmURL, }, $cand->{hmmDesc}, "(". $cand->{hmmId} . ")"),
                         "",
                         a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId"
                             . "&path=$cand->{pathway}&step=$cand->{step}&locusId=$locusSpec",
                             -title => "View alignments" },
                           int(0.5 + 100 * $cand->{hmmCoverage})."%"),
                         $cand->{hmmBits},
                         $linkOther, $otherIdentity, $otherBits ]);
        }
      }
      print table({-cellpadding=>2, -cellspacing=>0, -border=>1}, @tr), "\n";
    }

    # Show tools
    my @seqparts = $seq =~ /.{1,60}/g;
    my $newline = "%0A";
    print
      h3("Sequence Analysis Tools");
    my $URL = GeneURL($orgId,$locusSpec);
    print p("View",
            a({-href => $URL}, "$locusSpec"),
            "at", $orgs{$orgId}{gdb})
      if $URL ne "";
    print
      p(a({-href => "http://papers.genomics.lbl.gov/cgi-bin/litSearch.cgi?query=>${locusSpec}$newline$seq"},
          "PaperBLAST"),
        "(search for papers about homologs of this protein)"),
      p(a({-href => "http://www.ncbi.nlm.nih.gov/Structure/cdd/wrpsb.cgi?seqinput=>${locusSpec}$newline$seq"},
          "Search CDD"),
        "(the Conserved Domains Database, which includes COG and superfam)"),
      p(a({-href => "http://pfam.xfam.org/search/sequence?seqOpts=&ga=0&evalue=1.0&seq=$seq"},
        "Search PFam"),
        "(including for weak hits, up to E = 1)"),
      p("Predict protein localization: ",
        a({-href => "http://www.psort.org/psortb/results.pl?"
           . join("&",
                  "organism=bacteria",
                  "gram=negative",
                  "format=html",
                  "sendresults=display",
                  "email=",
                  "seqs=>${locusSpec}$newline$seq")},
          "PSORTb"),
        "(Gram negative bacteria)"),
      p("Predict transmembrane helices:",
        a({-href => "http://www.cbs.dtu.dk/cgi-bin/webface2.fcgi?"
           . join("&",
                  "configfile=/usr/opt/www/pub/CBS/services/TMHMM-2.0/TMHMM2.cf",
                  "outform=-noshort",
                  "SEQ=>${locusSpec}$newline$seq")},
          "TMHMM")),
      p("Check the SEED with",
      a({-href => "http://pubseed.theseed.org/FIG/seedviewer.cgi?page=FigFamViewer&fasta_seq=>${locusSpec}$newline$seq"},
        "FIGfam search")),
      h3("Sequence"),
      join("\n", "<pre>", @seqparts, "</pre>"), "\n";
  } elsif ($locusSpec ne "" && $step ne "") {
    # mode: Show alignments for a gene
    push @links, a({-href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$pathSpec&step=$step"},
                    "All candidates for step $step in", $orgs{$orgId}{genomeName});
    my @querycol = qw{step type query desc file sequence};
    my @queries = ReadTable("$queryPath/$pathSpec.query", \@querycol);
    my %curatedSeq = ();
    foreach my $query (@queries) {
      my $id = $query->{query};
      if ($query->{type} eq "curated") {
        $curatedSeq{$id} = $query->{sequence};
      } elsif ($query->{type} eq "uniprot") {
        $curatedSeq{"uniprot:".$id} = $query->{sequence};
      } elsif ($query->{type} eq "curated2") {
        $curatedSeq{"curated2:".$id} = $query->{sequence};
      }
    }
    my %hmmToFile = map { $_->{query} => $_->{file} } grep { $_->{type} eq "hmm" } @queries;
    my @cand = ReadSumCand($sumpre,$pathSpec);
    @cand = grep { $_->{orgId} eq $orgId && $_->{step} eq $step && $_->{locusId} eq $locusSpec} @cand;
    die "$locusSpec is not a candidate" unless @cand > 0;
    my $tmp = "/tmp/gapView.$pathSpec.$$";
    foreach my $cand (@cand) {
      if ($cand->{blastBits} > 0) {
        my @loci = (); # locusId, sysName, desc
        push @loci, [ $cand->{locusId}, $cand->{sysName}, $cand->{desc} ];
        push @loci, [ $cand->{locusId2}, $cand->{sysName2}, $cand->{desc2} ] if $cand->{locusId2} ne "";
        foreach my $row (@loci) {
          my ($locusId, $sysName, $desc) = @$row;
          # Should move the descShowCurated/idShowHit code above to a subroutine for showing what it hits
          my $curatedComment = "a characterized protein";
          $curatedComment = "from UniProt"
            if $cand->{curatedIds} =~ m/^uniprot:/;
          $curatedComment = "a curated, but not characterized, protein from Swiss-Prot"
            if $cand->{curatedIds} =~ m/^curated2:/;
          print p("Align candidate (subject)", b("$locusId $sysName"), ":", $desc,
                  "to curated sequence (query)", CuratedToLink($cand->{curatedIds}, $cand->{curatedDesc}),
                  "($curatedComment)");
          my $curatedSeq = $curatedSeq{ $cand->{curatedIds} };
          die "Unknown sequence for query " . $cand->{curatedIds}
            unless $curatedSeq;
          my $faaCurated = "$tmp.curated.faa";
          open(my $fhC, ">", $faaCurated) || die "Cannot write to $faaCurated";
          my @hitIds = split /,/, $cand->{curatedIds};
          print $fhC ">$hitIds[0]\n$curatedSeq\n";
          close($fhC) || die "Error writing to $faaCurated";
          my $faaCand = "$tmp.genome.faa";
          FetchSeqs("../bin/blast", $faafile, [$orgId.":".$locusId], $faaCand);
          my $bl2seq = "../bin/blast/bl2seq";
          die "No such executable: $bl2seq\n" unless -x $bl2seq;
          print "<pre>";
          system($bl2seq, "-p", "blastp", "-i", $faaCurated, "-j", $faaCand, "-e", 0.01, "-F", "m S") == 0
            || die "bl2seq failed: $!";
          unlink($faaCurated);
          unlink($faaCand);
          print "</pre>\n";
        }
        # Arguably, should show alignments to "other" as well
      }
      if ($cand->{hmmBits} ne "" && $cand->{hmmBits} > 0) {
        print p(b("Align locus",
                  HTML::Entities::encode($cand->{locusId}),
                  HTML::Entities::encode($cand->{sysName}),
                  HTML::Entities::encode("($cand->{desc})"),
                  br(), "to HMM $cand->{hmmId} ($cand->{hmmDesc})"));
        my $hmmfile = "$queryPath/" . $hmmToFile{$cand->{hmmId}};
        die "No hmm file for $cand->{hmmId}" unless exists $hmmToFile{$cand->{hmmId}};
        die "No file for $cand->{hmmId}: $hmmfile is missing\n" unless -e $hmmfile;
        my $hmmsearch = "../bin/hmmsearch";
        die "No such executable: $hmmsearch\n" unless -x $hmmsearch;
        my $faaCand = "$tmp.genome.faa";
        FetchSeqs("../bin/blast", $faafile, [$orgId.":".$cand->{locusId}], $faaCand);
        print "<pre>";
        system($hmmsearch, $hmmfile, $faaCand) == 0
          || die "hmmsearch failed: $!";
        print "</pre>\n";
        unlink($faaCand);
      }
    }
  } else {
    die "Unknown mode\n";
  }

  if ($orgId ne "") {
    push @links, a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId" },
                   "$setDesc in", $orgs{$orgId}{genomeName})
      if $pathSpec ne "" || $locusSpec ne "" || $findgene ne "";
    push @links, a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$pathSpec" },
                   "$pathDesc{$pathSpec} in $orgs{$orgId}{genomeName}")
      if $pathSpec ne "" && $step ne "";
    my @form1 = (start_form(-method => 'get', -action => "genomeSearch.cgi"),
                 hidden(-name => 'gid', -value => $orgs{$orgId}{gid}, -override => 1),
                 hidden(-name => 'gdb', -value => $orgs{$orgId}{gdb}, -override => 1),
                 a({ -title => "Find characterized proteins whose descriptions match"
                     . " and have homologs in this genome",
                     -href => "genomeSearch.cgi?gid=$orgs{$orgId}{gid}&gdb=$orgs{$orgId}{gdb}" },
                   "Curated BLAST:"),
                 textfield(-name => 'query', -value => '', -size => 30, -maxlength => 200),
                 submit("Go"),
                 end_form);
    push @links, join("\n", @form1);
    my @form2 = (start_form(-method => 'get', -action => 'gapView.cgi'),
                 hidden(-name => 'orgs', -value => $orgsSpec, -override => 1),
                 hidden(-name => 'set'),
                 hidden(-name => 'orgId'),
                 a({-title => "Search through the gene descriptions."
                    . " You can use % as a wild-card character"}, "Search annotations: "),
                 textfield(-name => 'findgene', -value => '', -size => 30, -maxlength => 200, -override => 1),
                 submit("Go"),
                 end_form);
    push @links, join("", @form2);
    push @links, join(" ",
                      a({ -href => OrgIdToURL($orgId) }, $orgs{$orgId}{genomeName}),
                      small('(' . $orgs{$orgId}{gid} . ')'),
                      "at", $orgs{$orgId}{gdb})
      unless $orgs{$orgId}{gdb} eq "local";
  }

  push @links, a({-href => "gapView.cgi?orgs=$orgsSpec&set=$set&path=$pathSpec&showdef=1" },
                 "Definition of $pathDesc{$pathSpec}")
    if $pathSpec ne "" && !param("showdef");
  push @links, a({-href => "gapView.cgi?orgs=$orgsSpec&set=$set&path=$pathSpec"},
                 "$pathDesc{$pathSpec} across $nOrgs  genomes")
    if $pathSpec ne "" && (param("showdef") || $orgId ne "") && @orgs > 1;
  if (!param('gaps') && $pathSpec eq "") {
    if ($orgId eq "") {
      push @links, a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&gaps=1" },
                     "Potential gaps across $nOrgs genomes and all pathways");
    } else {
      push @links, a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&gaps=1" },
                     "Potential gaps in", $orgs{$orgId}{genomeName});
    }
  }
  push @links, a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set"}, "All $nOrgs genomes and all pathways")
    unless ($orgId eq "" && $pathSpec eq "" && !param('gaps')) || @orgs == 1;

  print h3("Links"), start_ul(), li(\@links), end_ul
    if @links > 0;
  my $format = quotemeta("+%b %d %Y");
  my $dateQuery = `date -r $queryPath/date $format`;
  my $dateAnalysis = `date -r $sumpre.done $format`;
  chomp $dateAnalysis;
  chomp $dateQuery;
  print p("This analysis was run on $dateAnalysis. The underlying query files were built on $dateQuery.");
  print h3("Downloads"),
    start_ul(),
    li(a({-href => "$sumpre.cand"}, "Candidates"), "(tab-delimited)"),
    li(a({-href => "$sumpre.steps"}, "Steps"), "(tab-delimited)"),
    li(a({-href => "$sumpre.rules"}, "Rules"), "(tab-delimited)"),
    li(a({-href => "$orgpre.faa"}, "Protein sequences"), "(fasta format)"),
    li(a({-href => "$orgpre.org"}, "Organisms"), "(tab-delimited)"),
    li(a({-href => "$orgpre.org"}, "Organisms"), "(tab-delimited)");
  print li(a({-href => "$queryPath/$set.resources.tar.gz" }, "Input databases"),
           "(gzipped tar file)")
    if NewerThan("$queryPath/$set.resources.tar.gz", "$queryPath/date");
  print end_ul;
  Finish();
}

sub RuleToScore($) {
  my ($sumRule) = @_;
  die "Undefined input to RuleToScore" unless defined $sumRule;
  my $score = 2;
  $score = 1 if $sumRule->{nMed} > 0;
  $score = 0 if $sumRule->{nLo} > 0;
  return $score;
}

sub ScoreToStyle($) {
  my ($score) = @_;
  $score = 0 if $score eq "";
  my $color = $score > 1 ? "#007000" : ($score < 1 ? "#CC4444" : "#000000");
  return "color: $color; font-weight: bold;" if $score > 1;
  return "color: $color;";
}

sub ScoreToLabel($) {
  my ($score) = @_;
  $score = 0 if $score eq "";
  return $score > 1 ? "high confidence" : ($score < 1 ? "low confidence" : "medium confidence");
}

sub ShowScoreShort($) {
  my ($score) = @_;
  $score = 0 if $score eq "";
  return span({ -style => ScoreToStyle($score), -title => ScoreToLabel($score) },
              $score > 1 ? "hi" : ($score < 1 ? "lo" : "med"));
}

sub HMMToURL($) {
  my ($hmmId) = @_;
  if ($hmmId =~ m/^TIGR/) {
    return "http://tigrfams.jcvi.org/cgi-bin/HmmReportPage.cgi?acc=".$hmmId;
  } elsif ($hmmId =~ m/^PF/) {
    my $hmmIdShort = $hmmId; $hmmIdShort =~ s/[.]\d+$//;
    return "http://pfam.xfam.org/family/".$hmmIdShort;
  }
  return "";
}


sub GeneURL($$) {
  my ($orgId,$locusId) = @_;
  die unless exists $orgs{$orgId};
  my $gdb = $orgs{$orgId}{gdb};
  my $gid = $orgs{$orgId}{gid};
  if ($gdb eq "FitnessBrowser") {
    return "http://fit.genomics.lbl.gov/cgi-bin/singleFit.cgi?orgId=${gid}&locusId=${locusId}";
  } elsif ($gdb eq "MicrobesOnline") {
    return "http://www.microbesonline.org/cgi-bin/fetchLocus.cgi?locus=$locusId";
  } elsif ($gdb eq "UniProt") {
    return "http://www.uniprot.org/uniprot/$locusId";
  } elsif ($gdb eq "NCBI") {
    my $assembly = OrgToAssembly($orgId);
    if (exists $assembly->{prot}{$locusId}) {
      my $g = $assembly->{prot}{$locusId};
      return "https://www.ncbi.nlm.nih.gov/gene/?term=" . $g->{GeneID}
        if $g->{GeneID};
      if ($g->{genomic_accession} && $g->{start} && $g->{end}) {
        my $center = int(($g->{start} + $g->{end})/2);
        my ($left,$right) = ($center-5000,$center+5000);
        # The NCBI sequence viewer is smart enough to clip to valid regions
        return "https://www.ncbi.nlm.nih.gov/nuccore/$g->{genomic_accession}/scaffold?report=graph&v=$left:$right";
      }
      # No longer build PaperBLAST links
      #return "http://papers.genomics.lbl.gov/cgi-bin/litSearch.cgi?query=".$g->{"non-redundant_refseq"}
      #  if (exists $g->{"non-redundant_refseq"} && $g->{"non-redundant_refseq"}) {
    }
    return "";
  } elsif ($gdb eq "IMG") {
    return "https://img.jgi.doe.gov/cgi-bin/w/main.cgi?section=GeneDetail&page=geneDetail&gene_oid=$locusId";
  } elsif ($gdb eq "local") {
    return "";
  }
  die "Unknown genome database $gdb\n";
}

my $assembly = undef; # cached
sub OrgToAssembly($) {
  my ($orgId) = @_;
  die "Invalid orgId $orgId" unless exists $orgs{$orgId};
  my $gdb = $orgs{$orgId}{gdb};
  my $gid = $orgs{$orgId}{gid};

  if (!defined $assembly || $assembly->{gdb} ne $gdb || $assembly->{gid} ne $gid) {
    $assembly = CacheAssembly($gdb, $gid, $tmpDir)
      || die "Cannot fetch assembly $gid from database $gdb\n";
  }
  return $assembly;
}

sub ReadSumSteps($) {
  my ($sumpre) = @_;
  return ReadTable("$sumpre.steps",
                   qw{orgId gdb gid pathway step onBestPath score locusId sysName
                      score2 locusId2 sysName2});
}

# ReadSumCand(prefix to summary file, pathway)
# use an empty pathway argument to get candidates for all pathways
sub ReadSumCand($$) {
  my ($sumpre, $pathSpec) = @_;
  my @req = qw{orgId gdb gid step score locusId sysName desc locusId2 sysName2 desc2
               blastBits curatedIds identity blastCoverage blastScore curatedDesc
               hmmBits hmmId hmmCoverage hmmScore hmmDesc
               otherIds otherBits otherIdentity otherCoverage otherDesc};
  my @rows = ReadTable("$sumpre.cand", \@req);
  @rows = grep { $_->{pathway} eq $pathSpec } @rows
    if defined $pathSpec && $pathSpec ne "";
  return @rows;
}

# From a list of cands, to a hash of
# orgId => locusId => list of rows
sub SumCandToHash($) {
  my ($cands) = @_;
  my %out = ();
  foreach my $cand (@$cands) {
    push @{ $out{ $cand->{orgId} }{ $cand->{locusId} } }, $cand;
  }
  return \%out;
}

sub CandToOtherColumns($) {
  my ($cand) = @_;
  my $otherIdentity = "";
  $otherIdentity = span({ -title => "coverage: " . int(0.5 + 100 *$cand->{otherCoverage})."%"},
                        int(0.5 + $cand->{otherIdentity})."%")
    if $cand->{otherBits};
  my $descShowOther = $cand->{otherDesc}; $descShowOther =~ s/;;.*//;
  my @otherIds = split /,/, $cand->{otherIds};
  my $URLother = "";
    my $linkOther = "";
  if ($cand->{otherBits}) {
    $URLother = "http://papers.genomics.lbl.gov/cgi-bin/litSearch.cgi?query=" . $otherIds[0];
    my $idShowOther = $otherIds[0];
    $idShowOther =~ s/^.*://;
    $linkOther = a({-href => $URLother, -title => "view $idShowOther in PaperBLAST"}, $descShowOther);
  }
  return (small($linkOther), small($otherIdentity), small($cand->{otherBits}));
}

sub CuratedToLink($$) {
  my ($curatedIds, $curatedDesc) = @_;
  die "Undefined curatedIds" unless defined $curatedIds;
  die "Undefined curatedDesc" unless defined $curatedDesc;
  $curatedDesc =~ s/;;.*//;
  my ($first) = split /,/, $curatedIds;
  if ($first =~ m/^uniprot:/) {
    $first =~ s/^uniprot://;
    $curatedDesc =~ s/^(Sub|Rec)Name: Full=//;
    $curatedDesc =~ s/[{][A-Za-z0-9:|_. ;,-]+[}]//g;
    $curatedDesc =~ s/AltName:.*//;
    $curatedDesc =~ s/EC=/EC /g;
    $curatedDesc =~ s/ +;/;/g;
    $curatedDesc =~ s/;+ *$//;
  }
  my $unchar = $first =~ m/^curated2:/;
  my $uncharLabel = $unchar ? "(uncharacterized)" : "";
  $first =~ s/^curated2://;
  my $URL = "http://papers.genomics.lbl.gov/cgi-bin/litSearch.cgi?query=" . $first;
  my $idShowHit = $first;
  $idShowHit =~ s/^.*://;
  my $link = a({-href => $URL, -title => "View $idShowHit $uncharLabel in PaperBLAST"}, $curatedDesc);
  $link .= " (" . a({-title => join(" ",
                                    "This protein has not been studied experimentally.",
                                    "It is included in GapMind's database because its annotation",
                                    "was manually curated.")
                    }, "uncharacterized") . ")"
    if $unchar;
  return $link;
}

sub OrgIdToURL($) {
  my ($orgId) = @_;
  die "Invalid orgId" unless exists $orgs{$orgId};
  my $gdb = $orgs{$orgId}{gdb};
  my $gid = $orgs{$orgId}{gid};
  die unless $gdb && $gid;
  # Avoid running any queries or fetching the genome (via CacheAssembly)
  # if all we need is a link to the genome page
  return "https://www.ncbi.nlm.nih.gov/assembly/$gid"
    if $gdb eq "NCBI";
  return "http://fit.genomics.lbl.gov/cgi-bin/org.cgi?orgId=$gid"
    if $gdb eq "FitnessBrowser";
  return "http://www.microbesonline.org/cgi-bin/genomeInfo.cgi?tId=$gid"
    if $gdb eq "MicrobesOnline";
  # the other databases are trickier, so just fetch everything
  my $assembly = OrgToAssembly($orgId);
  return $assembly->{URL};
}

sub ProcessUpload($) {
  my ($fhUp) = @_;
  my $state = {};
  my %seq = (); # header => sequence
  my %ids = (); # ids seen already
  while (my ($header, $seq) = ReadFastaEntry($fhUp, $state, 1)) {
    return ('error' => "Invalid characters in sequence for $header -- only A-Z or * are allowed")
      unless $seq =~ m/^[A-Z*]+$/;
    my @pieces = split / /, $header;
    my $id = shift @pieces;
    return ('error' => "No identifier at beginning of header $header")
      unless defined $id && $id ne "";
    return ('error' => "Duplicate sequence for identifier $id")
      if exists $ids{$id};
    $ids{$id} = 1;
    $seq{$header} = $seq;
  }
  return ('error' => "Sorry, uploaded file is not a valid fasta file: $state->{error}")
    if exists $state->{error};
  return ('error' => "No input sequences in upload")
    if scalar(keys %seq) == 0;
  return ('error' => "Sorry, the input has too many sequences (the limit is $maxNSeqsK,000)")
    if scalar(keys %seq) > $maxNSeqs;

  my $totLen = 0;
  my $nNucChar = 0;
  foreach my $seq (values %seq) {
    $totLen += length($seq);
    $nNucChar += ($seq =~ tr/ACGTUN//);
  }
  return ('error' => "The uploaded sequences seem to be nucleotide sequences rather than protein sequences")
    if $nNucChar/ $totLen >= 0.9;

  my $assembly = AASeqToAssembly(\%seq, $tmpDir) || die;
  return ('gdb' => $assembly->{gdb}, 'gid' => $assembly->{gid});
}

# Given a row from the steps table (or undef),
# returns the HTML for locusId/sysName/score
# (including a link to the page for the gene)
# $cands should be a hash of orgId => locusId => list of candidates
sub ShowCandidatesForStep($$$$) {
  my ($orgsSpec, $set, $stepRow, $candHash) = @_;
  return ("","") unless defined $stepRow;
  my $orgId = $stepRow->{orgId} || die;
  my $locusHash = $candHash->{$orgId} || die;
  my @work = ();
  push @work, [ $stepRow->{locusId}, $stepRow->{sysName},  $stepRow->{score} ]
    if $stepRow->{locusId} ne "";
  push @work, [ $stepRow->{locusId2}, $stepRow->{sysName2}, $stepRow->{score2} ]
    if $stepRow->{locusId2} ne "";

  my @show = ();
  foreach my $work (@work) {
    my ($locusId,$sysName,$score) = @$work;
    # Create two links if this is a split hit
    my @sysNameParts = split /,/, $sysName;
    my @locusParts = split /,/, $locusId;
    die unless @locusParts > 0;
    my $locusPart1 = $locusParts[0];
    my @candRows = @{ $locusHash->{$locusPart1} };
    die "No candidate row for locus $locusPart1" unless @candRows > 0;
    my @parts = ();
    while (@locusParts > 0) {
      my $locus = shift @locusParts;
      my $sysName = shift @sysNameParts;
      my $desc = $candRows[0]{desc};
      if ($locus ne $locusPart1) {
        my @candRows2 = grep { $_->{locusId2} eq $locus } @candRows;
        die "No candidate row for locus $locusPart1 and locus2 $locus" unless @candRows2 > 0;
        $desc = $candRows2[0]{desc2};
      }
      my $title = ScoreToLabel($score);
      $title .= ", annotated as " . HTML::Entities::encode($desc)
        if $desc =~ m/[a-zA-Z0-9]/; # ignore empty descriptions
      push @parts, a({ -style => ScoreToStyle($score),
                       -title => $title,
                       -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&locusId=$locus" },
                     $sysName || $locus );
    }
    push @show, join(" " . a({-title => "split protein"}, "with") . " ", @parts);
  }
  while (@show < 2) {
    push @show, "";
  }
  return @show;
}

my %stepsCache = ();
sub GetStepsObj($$) {
  my ($stepPath, $path) = @_;
  die unless defined $path && $path ne "";
  $stepsCache{$path} = ReadSteps("$stepPath/$path.steps")
    unless exists $stepsCache{$path};
  return $stepsCache{$path};
}

sub StepRowToCurated($$) {
  my ($stepRow, $curatedGaps) = @_;
  my $p = $stepRow->{pathway};
  return $curatedGaps->{ $stepRow->{gid} }{$p}{ $stepRow->{step} }
    if exists $curatedGaps->{ $stepRow->{gid} }{$p}{ $stepRow->{step} };
  return $curatedGaps->{ $stepRow->{gid} }{$p}{""}
    if exists $curatedGaps->{ $stepRow->{gid} }{$p}{""} && $stepRow->{score} ne "2";
  return undef;
}

sub StepRowToCuratedComment($$) {
  my ($stepRow, $curatedGaps) = @_;
  my $c = StepRowToCurated($stepRow, $curatedGaps);
  return $c ? a({ -title => $c->{comment}, -style => "color: darkgreen;" },
                $c->{class}) : "";
}

sub ShowCuratedLong($) {
  my ($curatedGap) = @_;
  return "" unless $curatedGap;
  return p(i("Manual classification:"), $curatedGap->{class},
           br(),
           i("Rationale:"), $curatedGap->{comment});
}

sub LegendForColorCoding() {
  my @titles = ("Low confidence candidates are highly diverged, have low coverage of the characterized homolog, or are similar to proteins that have other functions.",
                "Medium confidence candidates are less than 40% identical to a characterized protein; or the alignment (to either a characterized protein or an HMM) had under 80% coverage; or the candidate was found by similarity to a uncharacterized (but well-curated) protein.",
                "High confidence candidates match an HMM or are over 40% similar to a characterized protein; and the alignment covers 80% of the characterized protein or the HMM; and the candidate is less similar to characterized proteins that have other functions.");
  my @showScores = map span({ -style => ScoreToStyle($_), -title => $titles[$_] },
                            ScoreToLabel($_)), (2,1,0);
  return p("Confidence:", @showScores)."\n";
}

sub ShowWarnings($$$$) {
  my ($warnings, $orgsSpec, $set, $orgIdFilter) = @_;
  my @warnShow = @$warnings;
  @warnShow = grep { $_->{orgId} eq $orgIdFilter } @warnShow if $orgIdFilter ne "";
  return if @warnShow == 0;
  print h3("Dependencies"), start_ul;
  foreach my $warn (@warnShow) {
    my $pathShow = a({-href => "gapView.cgi?orgs=$orgsSpec&set=$set&path=" . $warn->{pathway}
                      . "&orgId=" . $warn->{orgId} }, $warn->{pathway});
    my $gn = $orgs{ $warn->{orgId} }{genomeName};
    my $out = scalar(keys %orgs) > 1 && $orgIdFilter eq "" ? "In $gn, $pathShow" : $pathShow;
    $out .= " (using rule $warn->{rule})" if $warn->{rule} ne "all";
    my $reqShow = $warn->{requiredPath};
    my $reqPart = $warn->{requiredRule} || $warn->{requiredStep} || "";
    $reqShow .= ":" . $reqPart unless $reqPart eq "all";
    my $reqURL = "gapView.cgi?orgs=$orgsSpec&set=$set&path=" . $warn->{requiredPath}
      . "&orgId=" . $warn->{orgId};
    if ($warn->{not}) {
      $out .= " is not allowed with " . a({-href => $reqURL}, $reqShow);
    } else {
      $out .= " also requires " . a({ -href => $reqURL }, $reqShow)
        . ", which is not high-confidence";
    }
    $out .= ".";
    $out .= start_ul . li($warn->{comment}) . end_ul if $warn->{comment} ne "";
    print li($out);
  }
  print end_ul, "\n";
}

sub Finish() {
  my $email = 'funwithwords26@gmail.com';
  print <<END
<h3>About GapMind</h3>
<P>Each pathway is defined by a set of rules based on individual steps or genes. Candidates for each step are identified by using ublast against a database of characterized proteins or by using HMMer. Ublast hits may be split across two different proteins.

<P>A candidate for a step is "high confidence" if either:
<UL>
<LI>ublast finds a hit at above 40% identity and 80% coverage, and bits >= other bits+10
<LI>HMMer finds a hit with 80% coverage of the model, and either other identity < 40 or other coverage < 0.75
</UL>
where "other" refers to the best ublast hit to a sequence that is not annotated as performing this step (and is not "ignored").

<P>Otherwise, a candidate is "medium confidence" if either:
<UL>
<LI>ublast finds a hit at above 40% identity and 70% coverage (ignoring otherBits)
<LI>ublast finds a hit at above 30% identity and 80% coverage, and bits >= other bits
<LI>HMMer finds a hit (regardless of coverage or other bits)
</UL>
<P>Other blast hits with at least 50% coverage are "low confidence."
<P>Steps with no high- or medium-confidence candidates may be considered "gaps."
For the typical bacterium that can make all 20 amino acids, there are 1-2 gaps in amino acid biosynthesis pathways.
Gaps may be due to:
<UL>
<LI>our ignorance of proteins' functions,
<LI>omissions in the gene models,
<LI>frame-shift errors in the genome sequence, or
<LI>the organism lacks the pathway.
</UL>

<P>GapMind relies on the predicted proteins in the genome and does not search the six-frame translation. In most cases, you can search the six-frame translation by clicking on links to Curated BLAST for each step definition (in the per-step page).

<P>If you notice any errors or omissions in the step descriptions, or any questionable results, please
<A HREF="mailto:$email">let us know</A>.

<center>by <A HREF="http://morgannprice.org/">Morgan Price</A>,
<A HREF="http://genomics.lbl.gov/">Arkin group</A>,
Lawrence Berkeley National Laboratory</center>
END
    ;
  print end_html;
  exit(0);
}
