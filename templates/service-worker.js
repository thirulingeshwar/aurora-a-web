const CACHE_NAME = 'aurora-cache-v1';
const urlsToCache = [
  '/',
  '/login',
  '/manifest.json',
  '/logo.png'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    (async () => {
      // Claim clients immediately
      await self.clients.claim();
      
      // One-time update notification for version 0.75
      const notified = await getState('update-notified-0.75');
      if (!notified) {
        try {
          await self.registration.showNotification("🚀 Aurora Update", {
            body: "Aurora V.75 is updated to Version 0.75!",
            icon: '/logo.png',
            badge: '/logo.png',
            tag: 'app-update-0.75'
          });
          await saveState('update-notified-0.75', true);
        } catch (e) {
          console.error('Error showing activation notification:', e);
        }
      }
    })()
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});

// Shift timing reminder logic
let shiftSchedule = null;
let lastNotifiedDate = '';

// Student attendance reminder logic
let studentsList = [];
let markedStudentIds = [];

// Helper to save state to Cache API
async function saveState(key, data) {
  try {
    const cache = await caches.open('aurora-state');
    await cache.put('/state-' + key, new Response(JSON.stringify(data)));
  } catch (e) {
    console.error('Error saving state to Cache API:', e);
  }
}

// Helper to get state from Cache API
async function getState(key) {
  try {
    const cache = await caches.open('aurora-state');
    const response = await cache.match('/state-' + key);
    if (response) {
      return await response.json();
    }
  } catch (e) {
    console.error('Error reading state from Cache API:', e);
  }
  return null;
}

// Load state from Cache Storage at startup
async function loadState() {
  const savedShift = await getState('shiftSchedule');
  if (savedShift) shiftSchedule = savedShift;
  const savedDate = await getState('lastNotifiedDate');
  if (savedDate) lastNotifiedDate = savedDate;
  const savedStudents = await getState('studentsList');
  if (savedStudents) studentsList = savedStudents;
  const savedMarked = await getState('markedStudentIds');
  if (savedMarked) markedStudentIds = savedMarked;
}

function convertTo12Hour(time24) {
  if (!time24) return 'N/A';
  let [hours, minutes] = time24.split(':');
  let period = parseInt(hours) >= 12 ? 'PM' : 'AM';
  let hours12 = parseInt(hours) % 12;
  hours12 = hours12 === 0 ? 12 : hours12;
  return `${hours12}:${minutes} ${period}`;
}

self.addEventListener('message', event => {
  if (!event.data) return;
  
  if (event.data.type === 'SET_SHIFT') {
    shiftSchedule = event.data;
    saveState('shiftSchedule', shiftSchedule);
  }
  
  if (event.data.type === 'ATTENDANCE_MARKED') {
    lastNotifiedDate = event.data.date;
    saveState('lastNotifiedDate', lastNotifiedDate);
  }
  
  if (event.data.type === 'SET_STUDENTS') {
    studentsList = event.data.students || [];
    saveState('studentsList', studentsList);
  }
  
  if (event.data.type === 'SET_MARKED_STUDENTS') {
    markedStudentIds = event.data.markedStudentIds || [];
    saveState('markedStudentIds', markedStudentIds);
  }
});

// Background check timer running every 30 seconds
function startBackgroundCheck() {
  setInterval(async () => {
    if (!shiftSchedule || studentsList.length === 0) {
      await loadState();
    }
    
    const now = new Date();
    // Format today as YYYY-MM-DD
    const todayStr = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
    const currentHours = now.getHours();
    const currentMinutes = now.getMinutes();
    
    // Staff Shift Reminder Check
    if (shiftSchedule) {
      // Skip if they have already checked in today
      if (lastNotifiedDate !== todayStr) {
        const [startH, startM] = shiftSchedule.startTime.split(':').map(Number);
        
        // Trigger notification if current time is past or equal to shift start time
        if (currentHours > startH || (currentHours === startH && currentMinutes >= startM)) {
          self.registration.showNotification("⏰ Shift Reminder", {
            body: `Hi ${shiftSchedule.staffName}, it's ${shiftSchedule.startTime || '10:00 AM'}. Don't forget to mark your attendance!`,
            icon: '/logo.png',
            badge: '/logo.png',
            tag: 'shift-start-reminder',
            renotify: true,
            vibrate: [200, 100, 200]
          });
          // Mark as notified for today to prevent duplicate alerts
          lastNotifiedDate = todayStr;
          saveState('lastNotifiedDate', lastNotifiedDate);
        }
      }
    }
    
    // Student Shift Reminder Check
    if (studentsList && studentsList.length > 0) {
      let notifiedStudents = await getState('notifiedStudents') || { date: '', ids: [] };
      if (notifiedStudents.date !== todayStr) {
        notifiedStudents = { date: todayStr, ids: [] };
        await saveState('notifiedStudents', notifiedStudents);
      }
      
      for (const student of studentsList) {
        // Skip if they are marked today
        if (markedStudentIds && markedStudentIds.includes(student.id)) continue;
        
        // Skip if already notified today
        if (notifiedStudents.ids.includes(student.id)) continue;
        
        if (!student.startTime) continue;
        
        const [startH, startM] = student.startTime.split(':').map(Number);
        
        // Trigger notification if current time is past or equal to class start time
        if (currentHours > startH || (currentHours === startH && currentMinutes >= startM)) {
          self.registration.showNotification("⏰ Student Attendance", {
            body: `Please give attendance for ${student.name}. Class starts at ${convertTo12Hour(student.startTime)}.`,
            icon: '/logo.png',
            badge: '/logo.png',
            tag: `student-start-${student.id}`,
            renotify: true,
            vibrate: [200, 100, 200]
          });
          
          notifiedStudents.ids.push(student.id);
          await saveState('notifiedStudents', notifiedStudents);
        }
      }
    }
  }, 30000);
}

startBackgroundCheck();

// Handle notification click to open/focus the app
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clientList => {
      if (clientList.length > 0) {
        let client = clientList[0];
        for (let i = 0; i < clientList.length; i++) {
          if (clientList[i].focused) {
            return clientList[i];
          }
        }
        return client.focus();
      }
      return clients.openWindow('/');
    })
  );
});
