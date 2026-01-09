##############################################
# $Id: 99_MyUtils.pm 1932 2012-01-28 18:15:28Z martinp876 $
package main;

use strict;
use warnings;
use JSON;
use Data::Dumper;

sub MyUtils_Initialize {
  my ($hash) = @_;
}

# Enter you functions below _this_ line.

sub MqttSignalduino_DispatchFromJSON {
  my ($json_str, $name) = @_;
  
  if (!defined($json_str) || !defined($name)) {
    Log3 $name, 3, "MqttSignalduino_DispatchFromJSON: Missing arguments (JSON or Name)";
    return;
  }

  my $hash = $defs{$name};
  if (!defined($hash)) {
    Log3 $name, 3, "MqttSignalduino_DispatchFromJSON: Device $name not found";
    return;
  }

  my $data;
  eval {
    $data = decode_json($json_str);
  };
  if ($@) {
    Log3 $name, 3, "MqttSignalduino_DispatchFromJSON: JSON decode error: $@";
    return;
  }
  #print Dumper($data);

  $hash->{Clients}    = 'SD_WS:';
  $hash->{MatchList}  = { '12:SD_WS'            => '^W\d+x{0,1}#.*' };

  # Extract fields based on expected JSON structure from MQTT
  # The full dispatch message is now constructed by combining 'preamble' (e.g., W126#) and 'state' (e.g., HexData).
  
  my $rmsg = $data->{rawmsg} // undef;
  my $dmsg = $data->{payload} // undef; 
  my $rssi = $data->{metadata}->{rssi} // undef;
  my $id = $data->{protocol}->{id} // undef;
  my $freqafc = $data->{metadata}->{freqafc} // undef;

  if (!defined($dmsg)) {
     Log3 $name, 4, "MqttSignalduino_DispatchFromJSON: No dmsg found in JSON";
     return;
  }

  # Update hash with latest values
  #$hash->{RAWMSG} = $rmsg if (defined($rmsg));
  #$hash->{RSSI} = $rssi if (defined($rssi));
  
  # Prepare addvals similar to SIGNALduno_Dispatch
  my %addvals = (
    Protocol_ID => $id
  );
  
  if (defined($rmsg)) {
      $addvals{RAWMSG} = $rmsg;
  }
  if (defined($rssi)) {
      $addvals{RSSI} = $rssi;
  }
  if (defined($freqafc)) {
      $addvals{FREQAFC} = $freqafc;
  }

  Log3 $name, 5, "MqttSignalduino_DispatchFromJSON: Dispatching $dmsg";
  
  # Call FHEM Dispatch function
  Dispatch($hash, $dmsg, \%addvals);
}

1;
