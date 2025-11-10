#!/usr/bin/perl
use strict;
use warnings;
use JSON::PP;
use B;
use Sub::Util qw(subname);
use File::Spec;
use File::Basename qw(dirname);
use Cwd;
use lib './lib';
require SD_ProtocolData;
require SD_Protocols;

sub perl_to_python {
    my ($full) = @_;
    my ($func) = $full =~ /SD_Protocols::(.+)$/;
    return $full unless $func;   # Fallback, falls kein Match

    # Direkte Umwandlung zu Python-Klassenmethoden
    # Diese Namen entsprechen den Methoden in ManchesterMixin, PostdemodulationMixin, RSLMixin
    
    # mcBit2* → manchester.mcBit2*  (z.B. mcBit2Grothe bleibt mcBit2Grothe)
    if ($func =~ /^mcBit2(.+)$/) {
        return "manchester.$func";  # z.B. manchester.mcBit2Grothe
    }

    # postDemo_* → postdemodulation.postDemo_*
    if ($func =~ /^postDemo_(.+)$/) {
        return "postdemodulation.$func";  # z.B. postdemodulation.postDemo_EM
    }

    # decode_/encode_* → rsl_handler.<function>  (RSL Protocol)
    if ($func =~ /^(decode|encode)_(\w+)$/) {
        return "rsl_handler.$func";  # z.B. rsl_handler.decode_rsl
    }

    # Helper-Funktionen → helpers.<function>
    if ($func =~ /^(mc2dmc|bin_str_2_hex_str|dec_2_bin_ppari|mcraw|length_in_range)$/i) {
        return "helpers." . lc($func);  # Konvertiere zu lowercase für Python
    }

    # Konverter-Funktionen → helpers.<function> (ConvBresser_*, ConvLaCrosse, etc.)
    if ($func =~ /^Conv/) {
        return "helpers." . $func;
    }

    # Standard-Fallback für unbekannte Funktionen
    return "sd_protocols.$func";
}



sub sanitize {
    my ($data) = @_;

    if (ref($data) eq 'HASH') {
        my %copy;
        foreach my $key (keys %$data) {
            my $val = $data->{$key};

            if (ref($val) eq 'CODE') {
                my $full = subname($val);
                my $name = eval { B::svref_2object($val)->GV->NAME } || undef;

                my $resolved = $full;
                if ($full =~ /__ANON__/) {
                    $resolved = $name || "CODE_REF:$key";
                }

                # Dynamisches Mapping anwenden
                $copy{$key} = perl_to_python($resolved);
            }
            elsif (ref($val) eq 'Regexp') {
                $copy{$key} = "$val";
            }
            else {
                $copy{$key} = sanitize($val);
            }
        }
        return \%copy;
    }
    elsif (ref($data) eq 'ARRAY') {
        return [ map { sanitize($_) } @$data ];
    }
    else {
        return $data;
    }
}

# Hauptkonvertierung
my %cleaned;
foreach my $id (keys %SD_ProtocolData::protocols) {
    $cleaned{$id} = sanitize($SD_ProtocolData::protocols{$id});
}

my $version = $SD_ProtocolData::version || "unknown";

my $json = JSON::PP->new
    ->utf8
    ->pretty
    ->allow_blessed
    ->convert_blessed
    ->encode({
        version   => $version,
        protocols => \%cleaned
    });

use File::Spec;
use Cwd;

my $script_dir = dirname(Cwd::abs_path(__FILE__));
my $output_file = File::Spec->catfile($script_dir, '..', 'sd_protocols', 'protocols.json');

open my $fh, '>', $output_file or die "Kann Datei nicht schreiben: $!";
print $fh $json;
close $fh;

print "✅ Konvertierung abgeschlossen: protocols.json\n";
