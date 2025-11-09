#!/usr/bin/perl
use strict;
use warnings;
use JSON::PP;
use B;
use Sub::Util qw(subname);
use lib './lib';
require SD_ProtocolData;
require SD_Protocols;

sub perl_to_python {
    my ($full) = @_;
    my ($func) = $full =~ /SD_Protocols::(.+)$/;
    return $full unless $func;   # Fallback, falls kein Match

    my $fname = lcfirst($func);  # Funktionsname mit kleinem Anfangsbuchstaben

    # decode_/encode_-Fälle → Modul = Teil nach dem Unterstrich
    if ($fname =~ /^(decode|encode)_(\w+)$/) {
        return "$2.$fname";      # z.B. rsl.decode_rsl
    }

    # mcBit2-Fälle → Modul = Rest, Funktion = mc_bit2<rest>
    if ($fname =~ /^mcBit2(\w+)$/) {
        my $module = lc($1);
        my $funcname = "mc_bit2" . lc($1);
        return "$module.$funcname";  # z.B. grothe.mc_bit2grothe
    }

    # Standard-Fallback: Modul = gesamter Funktionsname
    return "$fname.$fname";
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

open my $fh, '>', 'protocols.json' or die "Kann Datei nicht schreiben: $!";
print $fh $json;
close $fh;

print "✅ Konvertierung abgeschlossen: protocols.json\n";
