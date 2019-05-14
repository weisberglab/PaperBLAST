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
# orgId -- overview of the organism
# path -- overview of the pathway across organisms
#	(if there is just one organism, shows that organism/pathway page instead)
# path & showdef -- detailed pathway definition (mostly, show the .steps file verbatim)
# orgId & path -- the pathway in the organism, with lists of rules and top candidates for each step
# orgId & path & step -- all candidates for the step, and the detailed definition of the step
# orgId & path & step & locusId -- show relevant alignments

use strict;
use CGI qw(:standard Vars start_ul);
use CGI::Carp qw(warningsToBrowser fatalsToBrowser);
use HTML::Entities;
use IO::Handle qw{autoflush};
use lib "../lib";
use Steps;
use pbutils;
use pbweb qw{start_page};
use FetchAssembly qw{CacheAssembly GetMatchingAssemblies GetMaxNAssemblies};
use File::stat;

sub ScoreToStyle($);
sub ScoreToLabel($);
sub ShowScoreShort($);
sub HMMToURL($);
sub GeneURL($$); # orgId (that is in %orgs), locusId
sub RuleToScore($);
sub LocusIdToFetchId($);
sub ReadCand($$);
sub OrgToAssembly($);
sub Finish(); # show "About the gap viewer" and exit

my $tmpDir = "../tmp"; # for CacheAssembly
my %orgs = (); # orgId => hash including gdb, gid, genomeName
my $nCPU = 6;

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
  my $banner = "Gap viewer for $setDesc";

  my @gdbs = ("NCBI", "IMG", "UniProt", "MicrobesOnline", "FitnessBrowser");
  my %gdb_labels1 = ("NCBI" => "NCBI assemblies",
                     "UniProt" => "UniProt proteomes",
                     "IMG" => "JGI/IMG genomes", "FitnessBrowser" => "Fitness Browser genomes");
  my %gdb_labels = map { $_ => exists $gdb_labels1{$_} ? $gdb_labels1{$_} : "$_ genomes"} @gdbs;

  my $orgsSpec = param('orgs');
  $orgsSpec = param('gdb') . "__" . param('gid')
    if !defined $orgsSpec && param('gdb') && param('gid');

  if (!defined $orgsSpec && param('gquery')) {
    # Genome query mode
    my $gquery = param('gquery');
    my $gdb = param('gdb') || die "Must specify gdb with gquery";
    die "Unknown genome database: $gdb\n"
      if !exists $gdb_labels{$gdb};
    start_page('title' => "Find gaps in $setDesc",
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
    # Front page mode
    start_page('title' => "Find gaps in $setDesc",
               'banner' => $banner,
               'bannerURL' => "gapView.cgi");
    print
      p("View gaps in",
        a({-href => "gapView.cgi?set=$set&orgs=orgs35"}, "35 bacteria"),
        "that grow in minimal media, or choose a genome to analyze:"),
      start_form(-method => 'get', -action => "gapView.cgi", -autocomplete => 'on'),
      hidden(-name => 'set', -value => $set, -override => 1),
      p("Genome database to search:",
        popup_menu(-name => 'gdb', -values => \@gdbs, -labels => \%gdb_labels, -default => $gdbs[0])),
      p(textfield(-name => 'gquery', -value => '', -size => 50, -maxlength => 200)),
      p(small("Example:", a({-href => "gapView.cgi?gdb=NCBI&gquery=Desulfovibrio vulgaris"}, "Desulfovibrio vulgaris"))),
      p(submit(-name => "findgenome", -value => 'Find Genome')),
      end_form;
    Finish();
  }

  $orgsSpec =~ m/^[a-zA-Z0-9._-]+$/ || die "Invalid orgs $orgsSpec";
  my $orgpre = "../tmp/$orgsSpec/orgs";
  my $sumpre = "../tmp/$orgsSpec/$set.sum";

  my $alreadyBuilt = NewerThan("$sumpre.done", "$queryPath/date");

  # Wait up to 5 minutes for a previously running job to finish
  if (! $alreadyBuilt
      && -e "$sumpre.begin"
      && stat("$sumpre.begin")->mtime >= time() - 5*60) {
    # Waiting mode
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
    # Computation mode

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
    my $time = 10 * scalar(@orgs);
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

  #else -- viewing mode
  my @orgs = ReadOrgTable("$orgpre.org");
  die "No organisms for $orgpre.org" unless @orgs > 0;
  %orgs = map { $_->{orgId} => $_ } @orgs;
  my $faafile = "$orgpre.faa";
  die "No such file: $faafile" unless -e $faafile;

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
    @path = ($pathSpec);
  }

  my $orgId = param("orgId"); # the organism specified, or, ""
  $orgId = "" if !defined $orgId;
  if ($orgId ne "") {
    die "Unknown orgId $orgId" unless exists $orgs{$orgId};
  }
  $orgId = $orgs[0]{orgId} if @orgs == 1;

  my $step = param("step");
  if (!defined $step) {
    $step = "";
  } else {
    $step =~ m/^[a-zA-Z0-9._'"-]+$/ || die "Invalid step $step";
  }

  my ($steps, $rules);
  if (@path == 1) {
    my $st = ReadSteps("$stepPath/$path[0].steps");
    $steps = $st->{steps};
    $rules = $st->{rules};
    die "Non-existent step $step" if $step ne "" && !exists $steps->{$step};
  }

  my $locusSpec = param("locusId");
  $locusSpec = "" if !defined $locusSpec;
  $locusSpec =~ m/^[a-zA-Z90-9_.-]*$/ || die "Invalid locus $locusSpec";

  my $title = $locusSpec ne "" ? "Aligments for a candidate for $step" : "Gaps";
  $title .= " for $pathDesc{$pathSpec}" if $pathSpec ne "" && $locusSpec eq "";
  $title = "Finding step $step for $pathDesc{$pathSpec}"
    if $step ne "" && $orgId ne "" && $pathSpec ne "" && $locusSpec eq "";
  $title .= " in $orgs{$orgId}{genomeName}"
    if $orgId ne "";
  $title = "Definition of $pathDesc{$pathSpec}" if $pathSpec ne "" && param("showdef");
  my $nOrgs = scalar(@orgs);
  start_page('title' => $title,
             'banner' => $banner,
             'bannerURL' => "gapView.cgi");
  print "\n";

  my @orgsSorted = sort { $a->{genomeName} cmp $b->{genomeName} } @orgs;
  my @ruleScoreLabels = ("has a gap", "may have a gap", "all steps were found");

  my @links = ();     # a list of items to put inside li at the bottom
  if ($pathSpec ne "" && param("showdef")) {
    # show the definition of this pathway
    my $stfile = "$stepPath/$pathSpec.steps";
    open (my $fh, "<", $stfile) || die "No such file: $stfile\n";
    my @lines = <$fh>;
    close($fh) || die "Error reading $fh";
    print pre(join("",@lines)), "\n";
    push @links, a({-href => "$queryPath/$pathSpec.query"}, "Table of queries for $pathSpec")
      . " (tab-delimited)";
  } elsif ($orgId eq "" && $pathSpec eq "") {
    # list of pathways
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
    # overview of this pathway across organisms
    print p("Analysis of pathway $pathSpec in", scalar(@orgs), "genomes"), "\n";
    my @sumRules = ReadTable("$sumpre.rules", qw{orgId gdb gid rule score nHi nMed nLo expandedPath});
    @sumRules = grep { $_->{pathway} eq $pathSpec && $_->{rule} eq "all" } @sumRules;
    my %orgAll = map { $_->{orgId} => $_ } @sumRules;
    my @sumSteps = ReadTable("$sumpre.steps", qw{orgId gdb gid step score locusId sysName});
    @sumSteps = grep { $_->{pathway} eq $pathSpec} @sumSteps;
    my %orgStep = ();           # orgId => step => row from sum.steps
    foreach my $row (@sumSteps) {
      $orgStep{$row->{orgId}}{$row->{step}} = $row;
    }
    my $st = ReadSteps("$stepPath/$pathSpec.steps");
    $steps = $st->{steps};
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
        push @show, a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$pathSpec&step=$step",
                        -style => ScoreToStyle($score),
                        -title => "$steps->{$step}{desc} (" . ScoreToLabel($score) . ")" },
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
  } elsif ($pathSpec eq "") {
    # overview of pathways for this organism
    my @hr = ("Pathway", span({-title=>"Best path"}, "Steps"));
    my @tr = ();
    push @tr, th({-valign => "top"}, \@hr);
    my @sumRules = ReadTable("$sumpre.rules", qw{orgId gdb gid rule score nHi nMed nLo expandedPath});
    my @all = grep { $_->{orgId} eq $orgId && $_->{rule} eq "all" } @sumRules;
    my %all = map { $_->{pathway} => $_ } @all;
    my @sumSteps = ReadTable("$sumpre.steps", qw{orgId gdb gid step score locusId sysName});
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

      my $st = ReadSteps("$stepPath/$path.steps");
      $steps = $st->{steps};
      foreach my $step (split / /, $all->{expandedPath}) {
        die "Unknown step $step for $path\n" unless exists $steps->{$step};
        my $score = exists $sumSteps{$path}{$step} ? $sumSteps{$path}{$step}{score} : 0;
        push @show, a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$path&step=$step",
                        -style => ScoreToStyle($score),
                        -title => "$steps->{$step}{desc} (" . ScoreToLabel($score) . ")" },
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
  } elsif ($step eq "") {
    # overview of this pathway in this organism, first the rules, then all of the steps
    my @sumRules = ReadTable("$sumpre.rules", qw{orgId gdb gid rule score nHi nMed nLo expandedPath});
    @sumRules = grep { $_->{orgId} eq $orgId && $_->{pathway} eq $pathSpec } @sumRules;
    my %sumRules = map { $_->{rule} => $_ } @sumRules;
    my @sumSteps = ReadTable("$sumpre.steps", qw{orgId gdb gid step score locusId sysName});
    @sumSteps = grep { $_->{orgId} eq $orgId && $_->{pathway} eq $pathSpec } @sumSteps;
    my %sumSteps = map { $_->{step} => $_ } @sumSteps;
    print h3(scalar(@sumRules), "rules"), "\n";
    print start_ul;
    foreach my $rule (reverse @sumRules) {
      my @stepList = split / /, $rule->{expandedPath};
      my @parts = ();
      foreach my $step (@stepList) {
        my $stepDef = $steps->{$step} || die "Invalid step $step";
        my $stepS = exists $sumSteps{$step} ? $sumSteps{$step} : {};
        my $score = $stepS->{score} || 0;
        my $label = ScoreToLabel($score);
        my $id = $stepS->{sysName} || $stepS->{locusId} || "";
        push @parts, a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$pathSpec&step=$step",
                         -style => ScoreToStyle($score),
                         -title => "$stepDef->{desc} -- $id ($label)" },
                       $step);
      }
      print li($rule->{rule}.":", @parts);
      print start_ul;
      foreach my $list (@{ $rules->{ $rule->{rule} } }) {
        my @parts = ();
        foreach my $part (@$list) {
          if (exists $steps->{$part}) {
            my $score = exists $sumSteps{$part} ? $sumSteps{$part}{score} : 0;
            push @parts, a({ -style => ScoreToStyle($score), -title => "$steps->{$part}{desc}",
                             -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$pathSpec&step=$part" },
                           $part);
          } elsif (exists $rules->{$part}) {
            my $score = RuleToScore($sumRules{$part});
            push @parts, span({ -style => ScoreToStyle($score), -title => "see rule for $part below" }, $part);
          } else {
            die "Unknown part $part";
          }
        }
        print li("from " . join(", ", @parts));
      }
      print end_ul, "\n";
    }
    print end_ul, "\n";
    my @stepsSorted = sort { $a->{i} <=> $b->{i} } (values %$steps);
    print h3(scalar(@stepsSorted) . " steps (" . scalar(@sumSteps) . " with candidates)"), "\n";
    my @tr = ();
    my @header = qw{Step Description Best-candidate 2nd-candidate};
    foreach (@header) {
      s/-/ /;
    }
    push @tr, Tr(th(\@header));
    # For each step, show the step name and description, the best candidate (if any), and the 2nd best candidate(s) if any
    # Use all of the steps that are defined, not just the ones in the rules file, as ones with no candidates are missing
    foreach my $stepS (@stepsSorted) {
      my $step = $stepS->{name};
      die "invalid step $step" unless exists $steps->{$step};
      my @cand = ();
      if (exists $sumSteps{$step}) {
        push @cand, [ $sumSteps{$step}{locusId}, $sumSteps{$step}{sysName}, $sumSteps{$step}{score} ]
          if $sumSteps{$step}{locusId} ne "";
        push @cand, [ $sumSteps{$step}{locusId2}, $sumSteps{$step}{sysName2}, $sumSteps{$step}{score2} ]
          if $sumSteps{$step}{locusId2} ne "";
      }
      my @show = ();
      foreach my $cand (@cand) {
        my ($locusId,$sysName,$score) = @$cand;
        # Create two links if this is a split hit
        my @sysNameParts = split /,/, $sysName;
        my @locusParts = split /,/, $locusId;
        my @parts = ();
        while (@locusParts > 0) {
          my $locus = shift @locusParts;
          my $sysName = shift @sysNameParts;
          push @parts, a({ -style => ScoreToStyle($score), -title => ScoreToLabel($score),
                           -href => GeneURL($orgId, $locus) },
                         $sysName || $locus );
        }
        push @show, join(" with ", @parts);
      }
      while (@show < 2) {
        push @show, "";
      }
      push @tr, Tr(td({-valign => "top" },
                      [ a({-href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$pathSpec&step=$step"}, $step),
                        $stepS->{desc},
                        $show[0], $show[1] ]));
    }
    print table({-cellpadding=>2, -cellspacing=>0, -border=>1}, @tr), "\n";
  } elsif ($locusSpec eq "") {
    # overview of this step in this organism
    my @cand = ReadCand($sumpre,$pathSpec);
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
        my $id = a({-href => GeneURL($orgId, $cand->{locusId}) },
                   $cand->{sysName} || $cand->{locusId} );
        my $desc = $cand->{desc};
        # HMM hits are based on the 1st ORF only so ignore the split when showing the HMM part
        my $id1 = $id;
        my $desc1 = $desc;
        if ($cand->{locusId2}) { # (this should only happen for BLAST hits)
          $id .= "; " . a({-href => GeneURL($orgId, $cand->{locusId2}) },
                          $cand->{sysName2} || $cand->{locusId2} );
          $desc .= "; " . $cand->{desc2};
        }
        my $otherIdentity = "";
        $otherIdentity = span({ -title => "coverage: " . int(0.5 + 100 *$cand->{otherCoverage})."%"},
                              int(0.5 + $cand->{otherIdentity})."%")
          if $cand->{otherBits};
        my $descShowOther = $cand->{otherDesc}; $descShowOther =~ s/;;.*//;
        my @otherIds = split /,/, $cand->{otherIds};
        my $URLother = "";
        my $idShowOther = "";
        my $linkOther = "";
        if ($cand->{otherBits}) {
          $URLother = "http://papers.genomics.lbl.gov/cgi-bin/litSearch.cgi?query=" . $otherIds[0];
          $idShowOther = $otherIds[0];
          $idShowOther =~ s/^.*://;
          $linkOther = a({-href => $URLother, -title => "view $idShowOther in PaperBLAST"}, $descShowOther);
        }
        if ($cand->{blastScore} ne "") {
          my $descShowCurated = $cand->{curatedDesc}; $descShowCurated =~ s/;;.*//;
          my @hitIds = split /,/, $cand->{curatedIds};
          if ($hitIds[0] =~ m/^uniprot:/) {
            $hitIds[0] =~ s/^uniprot://;
            $descShowCurated =~ s/^RecName: Full=//;
            $descShowCurated =~ s/[{][A-Za-z0-9:|_. ;,-]+[}]//g;
            $descShowCurated =~ s/AltName:.*//;
            $descShowCurated =~ s/EC=/EC /g;
            $descShowCurated =~ s/ +;/;/g;
            $descShowCurated =~ s/;+ *$//;
          }
          my $URL = "http://papers.genomics.lbl.gov/cgi-bin/litSearch.cgi?query=" . $hitIds[0];
          my $idShowHit = $hitIds[0];
          $idShowHit =~ s/^.*://;
          push @tr, Tr(td({-valign => "top"},
                          [ ShowScoreShort($cand->{blastScore}),
                            $id, $desc,
                            a({-href => $URL, -title => "View $idShowHit in PaperBLAST"}, $descShowCurated),
                            int(0.5 + $cand->{identity})."%",
                            a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$pathSpec&step=$step&locusId=$cand->{locusId}",
                                -title => "View alignments" },
                              int(0.5 + 100 * $cand->{blastCoverage})."%"),
                            $cand->{blastBits},
                            small($linkOther),
                            small($otherIdentity),
                            small($cand->{otherBits} > 0 ? $cand->{otherBits} : "")
                          ]));
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
                            small($linkOther),
                            small($otherIdentity),
                            small($cand->{otherBits} > 0 ? $cand->{otherBits} : "")
                          ]));
        }
      }
      print table({-cellpadding=>2, -cellspacing=>0, -border=>1}, @tr), "\n";
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
  } else {
    # Show alignments
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
      }
    }
    my %hmmToFile = map { $_->{query} => $_->{file} } grep { $_->{type} eq "hmm" } @queries;
    my @cand = ReadCand($sumpre,$pathSpec);
    @cand = grep { $_->{orgId} eq $orgId && $_->{step} eq $step && $_->{locusId} eq $locusSpec} @cand;
    die "$locusSpec is not a candidate" unless @cand > 0;
    my $assembly = OrgToAssembly($orgId);
    die unless -e $assembly->{faafile};
    if (! -e $assembly->{faafile} . ".pin") {
      my $formatdb = "../bin/blast/formatdb";
      die "No such executable: $formatdb" unless -x $formatdb;
      system($formatdb, "-p", "T", "-o", "T", "-i", $assembly->{faafile}) == 0
        || die "Formatting $assembly->{faafile} failed: $!\n";
    }
    my $tmp = "/tmp/gapView.$pathSpec.$$";
    foreach my $cand (@cand) {
      if ($cand->{blastBits} > 0) {
        my @loci = (); # locusId, sysName, desc
        push @loci, [ $cand->{locusId}, $cand->{sysName}, $cand->{desc} ];
        push @loci, [ $cand->{locusId2}, $cand->{sysName2}, $cand->{desc2} ] if $cand->{locusId2} ne "";
        foreach my $row (@loci) {
          my ($locusId, $sysName, $desc) = @$row;
          # Should move the descShowCurated/idShowHit code above to a subroutine for showing what it hits
          print p(b("Align candidate $locusId $sysName ($desc)", br(),
                    "to $cand->{curatedIds} ($cand->{curatedDesc})"));
          my $curatedSeq = $curatedSeq{ $cand->{curatedIds} };
          die "Unknown sequence for query " . $cand->{curatedIds}
            unless $curatedSeq;
          my $faaCurated = "$tmp.curated.faa";
          open(my $fhC, ">", $faaCurated) || die "Cannot write to $faaCurated";
          my @hitIds = split /,/, $cand->{curatedIds};
          print $fhC ">$hitIds[0]\n$curatedSeq\n";
          close($fhC) || die "Error writing to $faaCurated";
          my $faaCand = "$tmp.genome.faa";
          FetchSeqs("../bin/blast", $assembly->{faafile}, [LocusIdToFetchId($locusId)], $faaCand);
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
      if ($cand->{hmmBits} > 0) {
        print p(b("Align locus $cand->{locusId} $cand->{sysName} ($cand->{desc})",
                  br(), "to HMM $cand->{hmmId} ($cand->{hmmDesc})"));
        my $hmmfile = "$queryPath/" . $hmmToFile{$cand->{hmmId}};
        die "No hmm file for $cand->{hmmId}" unless exists $hmmToFile{$cand->{hmmId}};
        die "No file for $cand->{hmmId}: $hmmfile is missing\n" unless -e $hmmfile;
        my $hmmsearch = "../bin/hmmsearch";
        die "No such executable: $hmmsearch\n" unless -x $hmmsearch;
        my $faaCand = "$tmp.genome.faa";
        FetchSeqs("../bin/blast", $assembly->{faafile}, [LocusIdToFetchId($cand->{locusId})], $faaCand);
        print "<pre>";
        system($hmmsearch, $hmmfile, $faaCand) == 0
          || die "hmmsearch failed: $!";
        print "</pre>\n";
        unlink($faaCand);
      }
    }
  }

  push @links, a({-href => "gapView.cgi?orgs=$orgsSpec&set=$set&path=$pathSpec&showdef=1" },
                 "Definition of $pathDesc{$pathSpec}")
    if $pathSpec ne "" && !param("showdef");
  push @links, a({-href => "gapView.cgi?orgs=$orgsSpec&set=$set&path=$pathSpec"},
                 "Pathway $pathSpec across", scalar(@orgs), "genomes")
    if $pathSpec ne "" && (param("showdef") || $orgId ne "") && @orgs > 1;
  push @links, a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId" },
                 "All pathways for", $orgs{$orgId}{genomeName})
    if $orgId ne "" && $pathSpec ne "";
  my $inOrgLabel = "";
  $inOrgLabel = "in " . a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId" }, $orgs{$orgId}{genomeName})
    if @orgs > 1 && $orgId ne "";
  push @links, join(" ", "All steps for",
                    a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set&orgId=$orgId&path=$pathSpec" }, $pathSpec),
                    $inOrgLabel)
    if $orgId ne "" && $pathSpec ne "" && $step ne "";
  push @links,
    a({ -href => "http://papers.genomics.lbl.gov/cgi-bin/genomeSearch.cgi?gdb=$orgs{$orgId}{gdb}&gid=$orgs{$orgId}{gid}" },
      "Curated BLAST against", $orgs{$orgId}{genomeName})
      if $orgId ne "";
  push @links, join(" ",
                    "Genome of ",
                    a({-href => OrgToAssembly($orgId)->{URL} }, "$orgs{$orgId}{genomeName}"),
                    "(" . OrgToAssembly($orgId)->{gid} . ") at $orgs{$orgId}{gdb}")
    if $orgId ne "";
  push @links, a({ -href => "gapView.cgi?orgs=$orgsSpec&set=$set"}, "All $nOrgs genomes and all pathways")
    unless ($orgId eq "" && $pathSpec eq "") || @orgs == 1;
  print h3("Links"), start_ul(), li(\@links), end_ul
    if @links > 0;
  print h3("Downloads"), start_ul(),
    li(a({-href => "$sumpre.cand"}, "Candidates"), "(tab-delimited)"),
    li(a({-href => "$sumpre.steps"}, "Steps"), "(tab-delimited)"),
    li(a({-href => "$sumpre.rules"}, "Rules"), "(tab-delimited)"),
    li(a({-href => "$orgpre.faa"}, "Protein sequences"), "(fasta format)"),
    li(a({-href => "$orgpre.org"}, "Organisms"), "(tab-delimited)"),
    end_ul;
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
  my $color = $score > 1 ? "#007000" : ($score < 1 ? "#CC4444" : "#000000");
  return "color: $color; font-weight: bold;" if $score > 1;
  return "color: $color;";
}

sub ScoreToLabel($) {
  my ($score) = @_;
  return $score > 1 ? "high confidence" : ($score < 1 ? "low confidence" : "medium confidence");
}

sub ShowScoreShort($) {
  my ($score) = @_;
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
      if (exists $g->{"non-redundant_refseq"} && $g->{"non-redundant_refseq"}) {
        return "http://papers.genomics.lbl.gov/cgi-bin/litSearch.cgi?query=".$g->{"non-redundant_refseq"};
      }
      return "https://www.ncbi.nlm.nih.gov/gene/?term=" . $g->{GeneID}
        if $g->{GeneID};
      if ($g->{genomic_accession} && $g->{start} && $g->{end}) {
        my $center = int(($g->{start} + $g->{end})/2);
        my ($left,$right) = ($center-5000,$center+5000);
        # The NCBI sequence viewer is smart enough to clip to valid regions
        return "https://www.ncbi.nlm.nih.gov/nuccore/$g->{genomic_accession}/scaffold?report=graph&v=$left:$right";
      }
    }
    # else give up, no link; ideally should fetch the protein sequence and return a PaperBLAST link instead?
    return "";
  } elsif ($gdb eq "IMG") {
    return "https://img.jgi.doe.gov/cgi-bin/w/main.cgi?section=GeneDetail&page=geneDetail&gene_oid=$locusId";
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

sub ReadCand($$) {
  my ($sumpre, $pathSpec) = @_;
  my @req = qw{orgId gdb gid step score locusId sysName desc locusId2 sysName2 desc2
               blastBits curatedIds identity blastCoverage blastScore curatedDesc
               hmmBits hmmId hmmCoverage hmmScore hmmDesc
               otherIds otherBits otherIdentity otherCoverage otherDesc};
  my @rows = ReadTable("$sumpre.cand", \@req);
  return grep { $_->{pathway} eq $pathSpec } @rows;
}

# Convert an identifier into a form suitable for FetchSeqs (which relies on fastacmd)
sub LocusIdToFetchId($) {
  my ($locusId) = @_;
  $locusId = "lcl|" . $locusId if $locusId =~ m/^\d+$/;
  return $locusId;
}

sub Finish() {
  my $email = 'funwithwords26@gmail.com';
  print <<END
<h3>About the gap viewer</h3>
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
<P>Steps with no high- or medium-confidence candidates may be considered gaps.
For the typical bacterium that can make all 20 amino acids, there are 1-2 gaps in amino acid biosynthesis pathways.
Gaps may be due to:
<UL>
<LI>our ignorance of proteins' functions,
<LI>omissions in the gene models,
<LI>frame-shift errors in the genome sequence, or
<LI>the organism lacks the pathway.
</UL>

<P>The gap viewer relies on the predicted proteins in the genome and does not search the six-frame translation. In most cases, you can search the six-frame translation by clicking on links to Curated BLAST for each step definition (in the per-step page).

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
