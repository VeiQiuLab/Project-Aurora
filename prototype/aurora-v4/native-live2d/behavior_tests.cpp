#include "behavior.h"
#include <limits>
#include <cstdlib>
#include <string>
void require(bool value) { if(!value) std::abort(); }
int main() {
    using namespace aurora;
    const std::string parameters[]={"ParamAngleZ","ParamMouthOpenY"};
    auto at=[&](int i){return parameters[i];};
    require(parameterIndex(2,std::string("ParamMouthOpenY"),at)==1);
    require(parameterIndex(1,std::string("ParamMouthOpenY"),at)==-1);
    require(parameterIndex(0,std::string("ParamMouthOpenY"),at)==-1);
    int motion=1;
    require(optionalMotion([&](){return &motion;})==&motion);
    require(optionalMotion([]()->int*{return nullptr;})==nullptr);
    require(optionalMotion([]()->int*{throw 1;})==nullptr);
    require(mouthValue(0.5f,-2,4,true)==1);
    require(mouthValue(100,0,1,true)==1);
    require(mouthValue(-1,0,1,true)==0);
    require(mouthValue(1,-2,4,false)==-2);
    require(mouthValue(std::numeric_limits<float>::quiet_NaN(),0,1,true)==0);
    require(mouthValue(std::numeric_limits<float>::infinity(),0,1,true)==0);
    require(mouthValue(1,0,0,true)==0);
    float tilt=0;
    for(int i=0;i<100;i++) tilt=approach(tilt,tiltTarget(1),0.017f);
    require(tilt>4.99f);
    for(int state: {2,0,3}) {
        for(int i=0;i<100;i++) tilt=approach(tilt,tiltTarget(state),0.017f);
        require(std::abs(tilt)<0.001f);
    }
}
