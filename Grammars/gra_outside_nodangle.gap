grammar gra_outside_nodangle uses sig_outside_foldrna(axiom = evert) {
  evert = window(REGION0, outer_strong with collfilter2, REGION0) 
	    | makeplot(REGION0) //makeplot is a dummy function, containing a makro in pfunc algebra which is responsible for drawing the PS dot plot
        # h;
	
  include "Grammars/Parts/grapart_outside_basic.gap"

//usual inside nodangel grammar
  include "Grammars/Parts/grapart_basic.gap"
}