export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        base: '#070b12',
        panel: '#101a2b',
        panel2: '#15253f',
        accent: '#3dd9b4',
        warn: '#ff8f5a'
      },
      boxShadow: {
        glow: '0 10px 30px rgba(61, 217, 180, 0.12)'
      }
    }
  },
  plugins: []
}
