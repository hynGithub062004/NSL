tc qdisc replace dev eth1 root netem limit 1000 delay 5ms loss 0.1% rate 100Mbit
tc qdisc show dev eth1
