// Flat-shaded facets in their own colour (the logo's low-poly look), a little glow in the dark.
VARYING vec3 vColor;

void MAIN()
{
    BASE_COLOR = vec4(vColor, 1.0);
    ROUGHNESS = roughness;
    METALNESS = 0.0;
    SPECULAR_AMOUNT = shine;
    EMISSIVE_COLOR = vColor * glow;
}
