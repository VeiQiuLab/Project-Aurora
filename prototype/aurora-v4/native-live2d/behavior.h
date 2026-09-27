#pragma once
#include <algorithm>
#include <cmath>

// Pure parameter policy, independently testable without the proprietary SDK.
namespace aurora {
template<class Id, class Getter>
int parameterIndex(int count, Id id, Getter at) {
    for(int i=0;i<count;i++) if(at(i)==id)return i;
    return -1;
}
template<class Loader>
auto optionalMotion(Loader load) -> decltype(load()) {
    try {return load();} catch(...) {return nullptr;}
}
inline float mouthValue(float normalized, float minimum, float maximum, bool active) {
    if (!std::isfinite(minimum)) return 0.0f;
    if (!std::isfinite(maximum) || maximum <= minimum) return minimum;
    if (!active || !std::isfinite(normalized)) return minimum;
    return minimum + std::clamp(normalized, 0.0f, 1.0f) * (maximum - minimum);
}
inline float tiltTarget(int state) { return state == 1 ? 5.0f : 0.0f; }
inline float approach(float current, float target, float delta) {
    return current + (target-current) * (1.0f-std::exp(-std::clamp(delta,0.0f,0.1f)/0.12f));
}
}
