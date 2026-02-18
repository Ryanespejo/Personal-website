import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import './BabyCalendar.css'

const WEEKS = [
  { week:4, emoji:'🌰', fruit:'Poppy Seed', size:'0.04 in', trimester:1,
    development:'The fertilized egg has implanted in the uterus. The embryo is forming two layers of cells that will develop into organs and body parts.',
    mom:'You may miss your period this week. Some women experience light spotting called implantation bleeding.',
    milestones:['Implantation complete','Placenta forming','Amniotic sac developing'] },
  { week:5, emoji:'🫘', fruit:'Sesame Seed', size:'0.05 in', trimester:1,
    development:'The heart is starting to form and will begin beating soon. The neural tube (which becomes the brain and spinal cord) is developing.',
    mom:'Morning sickness may begin. Fatigue and tender breasts are common as hormones surge.',
    milestones:['Heart begins forming','Neural tube developing','Tiny tail present'] },
  { week:6, emoji:'🫐', fruit:'Sweet Pea', size:'0.25 in', trimester:1,
    development:'The heart is now beating about 110 times per minute. Small buds appear that will grow into arms and legs. Facial features begin forming.',
    mom:'Nausea may intensify. You might notice heightened sense of smell and food aversions.',
    milestones:['Heartbeat detectable','Arm & leg buds','Nose & mouth forming'] },
  { week:7, emoji:'🫐', fruit:'Blueberry', size:'0.5 in', trimester:1,
    development:'The brain is growing rapidly, producing about 100 new cells every minute. Hands and feet are emerging from the arm and leg buds.',
    mom:'Frequent urination begins as your uterus grows and presses on your bladder.',
    milestones:['100 brain cells/min','Hands & feet forming','Kidneys developing'] },
  { week:8, emoji:'🍇', fruit:'Raspberry', size:'0.63 in', trimester:1,
    development:"Baby is moving constantly though you can't feel it yet. Fingers and toes are forming. The upper lip and nose have formed.",
    mom:'Your blood volume is increasing. You may feel bloated and your waistband may start getting tight.',
    milestones:['Fingers forming','Spontaneous movement','Taste buds developing'] },
  { week:9, emoji:'🍒', fruit:'Cherry', size:'0.9 in', trimester:1,
    development:'All essential organs have begun forming. The tiny tail has disappeared. Baby now looks more human with distinct elbows and toes.',
    mom:'Mood swings are normal due to hormonal changes. Your skin might start to glow — or break out.',
    milestones:['All organs initiated','Tail gone','Muscles forming'] },
  { week:10, emoji:'🍓', fruit:'Strawberry', size:'1.2 in', trimester:1,
    development:"Baby's vital organs are fully formed and starting to function. Tiny nails are beginning to form on fingers and toes. Bones are hardening.",
    mom:'Your bump may start showing slightly. Veins might become more visible as blood volume increases by 50%.',
    milestones:['Organs functioning','Nails forming','Bones hardening'] },
  { week:11, emoji:'🫒', fruit:'Fig', size:'1.6 in', trimester:1,
    development:"Baby can open and close fists, and tiny tooth buds are appearing under the gums. The head makes up about half the body length.",
    mom:"Morning sickness may start to ease. You're approaching the end of the first trimester!",
    milestones:['Can make a fist','Tooth buds appear','Diaphragm developing'] },
  { week:12, emoji:'🍑', fruit:'Plum', size:'2.1 in', trimester:1,
    development:'Reflexes are developing — baby can curl toes, make sucking movements, and even get hiccups. Fingernails and toenails are forming.',
    mom:'Risk of miscarriage drops significantly. Many parents choose to share the news this week.',
    milestones:['Reflexes active','Can get hiccups','Vocal cords forming'] },
  { week:13, emoji:'🍋', fruit:'Lemon', size:'2.9 in', trimester:1,
    development:"Baby has unique fingerprints already! Organs are maturing and the intestines are moving from the umbilical cord into the abdomen.",
    mom:'Welcome to the second trimester! Energy often returns and nausea fades. The golden period begins.',
    milestones:['Unique fingerprints','Intestines in place','Vocal cords complete'] },
  { week:14, emoji:'🥝', fruit:'Kiwi', size:'3.4 in', trimester:2,
    development:'Baby is practicing breathing by inhaling amniotic fluid. Facial muscles are working — baby might be squinting or frowning.',
    mom:'You may notice increased appetite as nausea subsides. Enjoy eating again!',
    milestones:['Practicing breathing','Facial expressions','Lanugo hair growing'] },
  { week:15, emoji:'🍊', fruit:'Navel Orange', size:'4 in', trimester:2,
    development:'Baby can sense light even though eyelids are fused shut. Legs are growing longer than arms now. Skeleton is developing bones.',
    mom:'You might feel a fluttering sensation — those could be baby\'s first movements (quickening)!',
    milestones:['Senses light','Skeleton forming','Legs longer than arms'] },
  { week:16, emoji:'🥑', fruit:'Avocado', size:'4.6 in', trimester:2,
    development:"Baby's heart is pumping about 25 quarts of blood per day. The eyes are working and can slowly move. Toenails are starting to grow.",
    mom:'The famous pregnancy glow may appear thanks to increased blood flow and hormones.',
    milestones:['Heart pumps 25 qt/day','Eyes can move','Toenails growing'] },
  { week:17, emoji:'🥕', fruit:'Pear', size:'5.1 in', trimester:2,
    development:"Fat is starting to form under baby's skin, which will help with temperature regulation. Sweat glands are developing.",
    mom:'You may start sleeping on your side more comfortably. A pregnancy pillow might become your best friend.',
    milestones:['Fat forming','Sweat glands','Umbilical cord strengthening'] },
  { week:18, emoji:'🫑', fruit:'Bell Pepper', size:'5.6 in', trimester:2,
    development:"Baby can yawn, hiccup, and even suck their thumb! If you're having a girl, the uterus and fallopian tubes are formed.",
    mom:"You'll likely feel definite kicks and movements now. Your partner might be able to feel them too!",
    milestones:['Can yawn & suck thumb','Ears in final position','Myelin forming'] },
  { week:19, emoji:'🥭', fruit:'Mango', size:'6 in', trimester:2,
    development:"A waxy coating called vernix caseosa covers baby's skin to protect it from the amniotic fluid. Sensory development is exploding.",
    mom:"Anatomy scan week! You might find out the sex. Enjoy seeing your baby on the ultrasound screen.",
    milestones:['Vernix coating','Senses developing rapidly','Can hear sounds'] },
  { week:20, emoji:'🍌', fruit:'Banana', size:'6.5 in', trimester:2,
    development:"You're halfway there! Baby can swallow and is producing meconium. The nervous system is connecting millions of neurons.",
    mom:"Your uterus is at belly button level. You're officially showing!",
    milestones:['HALFWAY! 🎉','Can swallow','Neurons connecting rapidly'] },
  { week:21, emoji:'🥕', fruit:'Carrot', size:'10.5 in', trimester:2,
    development:"Baby's movements are more coordinated. Eyebrows and eyelids are fully formed. The bone marrow starts producing blood cells.",
    mom:'You may experience Braxton Hicks contractions — your body is practicing for delivery.',
    milestones:['Coordinated movement','Eyebrows formed','Bone marrow active'] },
  { week:22, emoji:'🌽', fruit:'Corn on the Cob', size:'11 in', trimester:2,
    development:'Baby looks like a miniature newborn. The lips and eyes are more defined. The pancreas is developing steadily.',
    mom:'Stretch marks might start appearing. Staying hydrated and moisturized can help.',
    milestones:['Looks like a newborn','Lips defined','Grip strength increasing'] },
  { week:23, emoji:'🥦', fruit:'Large Mango', size:'11.4 in', trimester:2,
    development:'Baby can hear your voice, heartbeat, and outside sounds. Lungs are developing surfactant needed for breathing outside the womb.',
    mom:'You might notice baby responding to loud sounds or music with kicks.',
    milestones:['Hears your voice','Lung surfactant forming','Skin translucent'] },
  { week:24, emoji:'🫑', fruit:'Cantaloupe', size:'11.8 in', trimester:2,
    development:"Baby's face is almost fully formed with eyelashes, eyebrows, and hair. The inner ear is developed — baby has a sense of balance.",
    mom:'Viability milestone — baby has a fighting chance if born early with medical intervention.',
    milestones:['Viability milestone','Has eyelashes','Sense of balance'] },
  { week:25, emoji:'🥥', fruit:'Cauliflower', size:'13.6 in', trimester:2,
    development:'Baby is gaining more fat and filling out. The nostrils begin to open and practice breathing continues. Skin is becoming less wrinkled.',
    mom:'You may notice more frequent heartburn and shortness of breath as baby pushes up.',
    milestones:['Nostrils opening','More body fat','Startle reflex active'] },
  { week:26, emoji:'🥬', fruit:'Lettuce Head', size:'14 in', trimester:2,
    development:"Baby's eyes are opening for the first time! They can see light filtering through. The immune system is absorbing your antibodies.",
    mom:'Third trimester is right around the corner. Nesting instincts might be kicking in.',
    milestones:['Eyes open! 👀','Absorbing antibodies','Brain waves active'] },
  { week:27, emoji:'🥦', fruit:'Head of Broccoli', size:'14.4 in', trimester:2,
    development:'Baby sleeps and wakes on a regular schedule. The brain is extremely active with new neural connections forming constantly.',
    mom:"Welcome to the third trimester! You may notice baby's sleep/wake patterns.",
    milestones:['Sleep/wake cycle','Brain very active','Can taste flavors'] },
  { week:28, emoji:'🍆', fruit:'Eggplant', size:'14.8 in', trimester:3,
    development:"Baby can blink and has developed REM sleep — meaning baby might be dreaming! Brain tissue is increasing rapidly.",
    mom:'Kick counts become important. You should feel about 10 movements in 2 hours.',
    milestones:['Can dream (REM)','Can blink','Rapid brain growth'] },
  { week:29, emoji:'🎃', fruit:'Butternut Squash', size:'15.2 in', trimester:3,
    development:"Baby's muscles and lungs are maturing. Bones are fully developed but still soft. Baby is getting more cramped in there!",
    mom:'You might feel more tired again as baby grows and demands more energy.',
    milestones:['Muscles maturing','Soft bones formed','Head is growing'] },
  { week:30, emoji:'🥒', fruit:'Cucumber', size:'15.7 in', trimester:3,
    development:'Baby\'s brain is getting wrinklier (more surface area = more brain power). Red blood cells are now fully forming in the bone marrow.',
    mom:'Trouble sleeping is common. Finding comfortable positions gets harder.',
    milestones:['Brain surface area ↑','Red blood cells forming','3 lbs now'] },
  { week:31, emoji:'🥥', fruit:'Coconut', size:'16.2 in', trimester:3,
    development:'Baby can process information from all five senses now. The irises can dilate and constrict in response to light.',
    mom:"You may notice more Braxton Hicks. Baby's kicks feel stronger and more pronounced.",
    milestones:['All 5 senses active','Pupils react to light','Rapid weight gain'] },
  { week:32, emoji:'🍈', fruit:'Jicama', size:'16.7 in', trimester:3,
    development:'Baby is practicing breathing, swallowing, sucking, and kicking — all skills needed after birth. Toenails are fully formed.',
    mom:'You may feel breathless as baby pushes against your diaphragm. Baby might drop lower soon.',
    milestones:['Practicing life skills','Toenails complete','Downy hair shedding'] },
  { week:33, emoji:'🍍', fruit:'Pineapple', size:'17.2 in', trimester:3,
    development:"Baby's immune system is getting a boost from you. The bones are hardening everywhere except the skull — it needs to stay flexible for birth.",
    mom:'Increased pressure on your bladder means even more bathroom trips. Hang in there!',
    milestones:['Immune system boost','Skull stays soft','Antibodies transferring'] },
  { week:34, emoji:'🍈', fruit:'Cantaloupe Melon', size:'17.7 in', trimester:3,
    development:"Baby's lungs and central nervous system are maturing. The vernix coating is thickening. If born now, baby would likely be healthy with some NICU time.",
    mom:'Fatigue and swelling are normal. Elevate your feet when you can.',
    milestones:['Lungs maturing','Vernix thickening','Central nervous system developing'] },
  { week:35, emoji:'🍯', fruit:'Honeydew Melon', size:'18.2 in', trimester:3,
    development:"Baby's kidneys are fully developed and the liver can process waste. Most babies settle into a head-down position this week.",
    mom:'Baby is running out of room! Movements feel more like rolls and wiggles than kicks.',
    milestones:['Kidneys fully developed','Head-down position','5.25 lbs now'] },
  { week:36, emoji:'🥬', fruit:'Romaine Lettuce', size:'18.7 in', trimester:3,
    development:'Baby is shedding the lanugo (fine body hair) and vernix. Fat continues to accumulate, filling out those adorable arm and leg rolls.',
    mom:'Your cervix may begin to dilate and efface. Weekly checkups usually start now.',
    milestones:['Shedding lanugo','Gaining cute chub','Digestive system ready'] },
  { week:37, emoji:'🥬', fruit:'Swiss Chard Bunch', size:'19.1 in', trimester:3,
    development:'Baby is considered early term! Practicing inhaling and exhaling amniotic fluid. Firm grasp developed — baby will grab your finger!',
    mom:'Nesting instincts may be in full force. You might suddenly want to clean and organize everything.',
    milestones:['Early term! 🎉','Strong grasp','Lungs nearly mature'] },
  { week:38, emoji:'🎃', fruit:'Mini Pumpkin', size:'19.6 in', trimester:3,
    development:"Baby's organs are fully mature and ready for life outside. The brain and nervous system are fine-tuning. Meconium fills the intestines.",
    mom:"You might experience the 'bloody show' or lose your mucus plug — signs labor could be near.",
    milestones:['Organs fully mature','Brain fine-tuning','Tear ducts developed'] },
  { week:39, emoji:'🍉', fruit:'Small Watermelon', size:'20 in', trimester:3,
    development:'Baby is full term! Brain development is incredible — it\'s grown 30% in the last few weeks. Baby is coated in new skin cells.',
    mom:'You might feel a burst of energy (nesting!) or feel very ready to be done. Both are normal!',
    milestones:['Full term! 🎉','Brain grew 30%','New skin forming'] },
  { week:40, emoji:'🍉', fruit:'Watermelon', size:'20.2 in', trimester:3,
    development:'Baby is ready to meet you! Average weight is about 7.5 lbs. The skull bones are not yet fused to allow passage through the birth canal.',
    mom:'Due date week! Only about 5% of babies arrive on their actual due date. Baby will come when ready!',
    milestones:['DUE DATE! 🎉🎉🎉','~7.5 lbs','Ready for the world'] },
]

function Modal({ index, onClose, onNav }) {
  const w = WEEKS[index]
  const progress = ((w.week - 4) / 36) * 100
  const triClass = w.trimester === 1 ? 't1' : w.trimester === 2 ? 't2' : 't3'
  const triName = w.trimester === 1 ? '1st Trimester' : w.trimester === 2 ? '2nd Trimester' : '3rd Trimester'

  return (
    <div className="bc-modal-overlay open" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="bc-modal">
        <button className="bc-modal-close" onClick={onClose}>&times;</button>
        <span key={w.week} className="bc-modal-emoji">{w.emoji}</span>
        <div className="bc-modal-week">Week {w.week}</div>
        <div className="bc-modal-fruit-name">{w.fruit}</div>
        <div className="bc-modal-size">{w.size}</div>
        <div style={{ textAlign: 'center' }}>
          <span className={`bc-tri-badge ${triClass}`}>{triName}</span>
        </div>
        <div className="bc-progress-bar">
          <div className="bc-progress-fill" style={{ width: `${progress}%` }} />
        </div>

        <div className="bc-modal-section">
          <h3>👶 Baby&apos;s Development</h3>
          <p>{w.development}</p>
        </div>
        <div className="bc-modal-section">
          <h3>🤰 What Mom Might Feel</h3>
          <p>{w.mom}</p>
        </div>
        <div className="bc-modal-section">
          <h3>⭐ Key Milestones</h3>
          <div className="bc-tags">
            {w.milestones.map((m, i) => (
              <span key={m} className={`bc-tag${i === 0 ? ' highlight' : i === 1 ? ' pink' : ''}`}>{m}</span>
            ))}
          </div>
        </div>

        <div className="bc-modal-nav">
          <button disabled={index === 0} onClick={() => onNav(-1)}>
            &larr; Week {index > 0 ? WEEKS[index - 1].week : ''}
          </button>
          <button disabled={index === WEEKS.length - 1} onClick={() => onNav(1)}>
            Week {index < WEEKS.length - 1 ? WEEKS[index + 1].week : ''} &rarr;
          </button>
        </div>
      </div>
    </div>
  )
}

export default function BabyCalendar() {
  const [filter, setFilter] = useState('all')
  const [modalIdx, setModalIdx] = useState(null)

  const filtered = filter === 'all' ? WEEKS : WEEKS.filter(w => w.trimester === parseInt(filter))

  const openModal = useCallback(weekIndex => {
    setModalIdx(weekIndex)
    document.body.style.overflow = 'hidden'
  }, [])

  const closeModal = useCallback(() => {
    setModalIdx(null)
    document.body.style.overflow = ''
  }, [])

  const navModal = useCallback(dir => {
    setModalIdx(i => Math.max(0, Math.min(WEEKS.length - 1, i + dir)))
  }, [])

  useEffect(() => {
    if (modalIdx === null) return
    const handler = e => {
      if (e.key === 'Escape') closeModal()
      if (e.key === 'ArrowLeft') navModal(-1)
      if (e.key === 'ArrowRight') navModal(1)
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [modalIdx, closeModal, navModal])

  // Cleanup overflow on unmount
  useEffect(() => {
    return () => { document.body.style.overflow = '' }
  }, [])

  return (
    <div className="bc-page">
      <Link to="/" className="bc-back-link">&larr; back</Link>

      <div className="bc-hero">
        <h1>how big is <span>baby</span>?</h1>
        <p>tap a week to see what fruit your baby is the size of, what&apos;s developing, and fun details</p>
      </div>

      <div className="bc-trimester-nav">
        {[['all', 'All Weeks'], ['1', '1st Trimester'], ['2', '2nd Trimester'], ['3', '3rd Trimester']].map(([val, label]) => (
          <button
            key={val}
            className={`bc-tri-btn${filter === val ? ' active' : ''}`}
            data-tri={val}
            onClick={() => setFilter(val)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="bc-weeks-grid">
        {filtered.map((w, i) => (
          <div
            key={w.week}
            className="bc-week-card"
            style={{ animationDelay: `${i * 0.04}s` }}
            onClick={() => openModal(WEEKS.indexOf(w))}
          >
            <span className="bc-fruit-emoji">{w.emoji}</span>
            <div className="bc-week-num">Week {w.week}</div>
            <div className="bc-fruit-name">{w.fruit}</div>
            <div className="bc-size-text">{w.size}</div>
          </div>
        ))}
      </div>

      {modalIdx !== null && (
        <Modal index={modalIdx} onClose={closeModal} onNav={navModal} />
      )}
    </div>
  )
}
