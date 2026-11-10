tc qdisc replace dev eth1 root netem limit 1000 delay 1ms loss 0.01% rate 30Mbit
tc qdisc show dev eth1
